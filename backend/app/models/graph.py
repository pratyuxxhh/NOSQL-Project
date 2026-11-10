"""The FraudMesh graph data model as typed Python.

Node labels, relationship types and allowed values live here so that Cypher
queries and API code refer to one definition. The Pydantic models describe the
properties stored on each node; Neo4j Community has no existence constraints, so
these models are what guarantee required properties are present.

Full explanation: docs/data-model.md
"""

from datetime import datetime
from enum import StrEnum
from typing import Annotated

from pydantic import BaseModel, Field


# -----------------------------------------------------------------------------
# Labels and relationship types
# -----------------------------------------------------------------------------


class NodeLabel(StrEnum):
    USER = "User"
    ACCOUNT = "Account"
    DEVICE = "Device"
    CARD = "Card"
    ADDRESS = "Address"
    PHONE = "Phone"
    MERCHANT = "Merchant"
    TRANSACTION = "Transaction"
    FRAUD_FLAG = "FraudFlag"
    ANALYST = "Analyst"
    RING = "Ring"
    ALERT = "Alert"


class RelType(StrEnum):
    # The four relationships named in the project synopsis.
    TRANSACTED_WITH = "TRANSACTED_WITH"  # Account -> Account | Merchant
    SHARED_DEVICE = "SHARED_DEVICE"  # Account - Account (derived)
    SHARED_ADDRESS = "SHARED_ADDRESS"  # Account - Account (derived)
    FLAGGED_BY = "FLAGGED_BY"  # Account | Transaction -> FraudFlag | Analyst
    # Further derived account-to-account links.
    SHARED_CARD = "SHARED_CARD"
    SHARED_PHONE = "SHARED_PHONE"
    # Supporting structure.
    OWNS = "OWNS"  # User -> Account
    USES_DEVICE = "USES_DEVICE"  # Account -> Device
    USES_CARD = "USES_CARD"  # Account -> Card
    LIVES_AT = "LIVES_AT"  # User -> Address
    HAS_PHONE = "HAS_PHONE"  # User -> Phone
    INITIATED = "INITIATED"  # Account -> Transaction
    PAID_TO = "PAID_TO"  # Transaction -> Merchant | Account
    MEMBER_OF = "MEMBER_OF"  # Account -> Ring
    # Alert links (added by FraudMesh for F8).
    ABOUT = "ABOUT"  # Alert -> Account | Transaction | Ring
    ASSIGNED_TO = "ASSIGNED_TO"  # Alert -> Analyst


# Derived Account-Account edges and the attribute node each is derived from.
# Device and Card hang off the Account; Address and Phone hang off the owning User.
# These edges are what ring detection and risk propagation traverse.
SHARED_RELATIONSHIPS: dict[RelType, NodeLabel] = {
    RelType.SHARED_DEVICE: NodeLabel.DEVICE,
    RelType.SHARED_CARD: NodeLabel.CARD,
    RelType.SHARED_ADDRESS: NodeLabel.ADDRESS,
    RelType.SHARED_PHONE: NodeLabel.PHONE,
}


# -----------------------------------------------------------------------------
# Allowed values
# -----------------------------------------------------------------------------


class KycStatus(StrEnum):
    PENDING = "PENDING"
    VERIFIED = "VERIFIED"
    REJECTED = "REJECTED"


class AccountType(StrEnum):
    SAVINGS = "SAVINGS"
    CURRENT = "CURRENT"
    WALLET = "WALLET"
    CREDIT = "CREDIT"


class AccountStatus(StrEnum):
    ACTIVE = "ACTIVE"
    FROZEN = "FROZEN"
    CLOSED = "CLOSED"


class CardType(StrEnum):
    DEBIT = "DEBIT"
    CREDIT = "CREDIT"
    PREPAID = "PREPAID"


class RiskTier(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"


class Channel(StrEnum):
    CARD = "CARD"
    UPI = "UPI"
    NETBANKING = "NETBANKING"
    WALLET = "WALLET"
    ATM = "ATM"


class TransactionStatus(StrEnum):
    APPROVED = "APPROVED"
    DECLINED = "DECLINED"
    PENDING = "PENDING"


class FlagSource(StrEnum):
    """Automated flag sources. A manual flag needs no FraudFlag node: its
    FLAGGED_BY relationship points straight at the Analyst who raised it."""

    RULE = "RULE"  # a rule score crossed the threshold
    RING = "RING"  # member of a ring confirmed as fraud
    PROPAGATION = "PROPAGATION"  # propagated risk crossed the threshold


class RingAlgorithm(StrEnum):
    LOUVAIN = "louvain"
    LPA = "lpa"


class RingStatus(StrEnum):
    NEW = "NEW"
    UNDER_REVIEW = "UNDER_REVIEW"
    CONFIRMED_FRAUD = "CONFIRMED_FRAUD"
    FALSE_POSITIVE = "FALSE_POSITIVE"


class AlertType(StrEnum):
    HIGH_RULE_SCORE = "HIGH_RULE_SCORE"
    RING_DETECTED = "RING_DETECTED"
    PROPAGATED_RISK = "PROPAGATED_RISK"
    LINKED_TO_FRAUD = "LINKED_TO_FRAUD"


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class AlertStatus(StrEnum):
    OPEN = "OPEN"
    ACK = "ACK"
    RESOLVED = "RESOLVED"


# -----------------------------------------------------------------------------
# Node property models
#
# Score scales: Transaction.rule_score / final_score are 0-100 (per transaction).
# Account.risk_score / propagated_risk are probabilities in 0-1 (per account),
# because noisy-OR aggregation needs values in [0, 1].
# -----------------------------------------------------------------------------

Probability = Annotated[float, Field(ge=0.0, le=1.0)]


class User(BaseModel):
    id: str
    name: str
    email: str
    phone: str  # masked for display, e.g. "******4321"; the full number is only hashed on Phone
    created_at: datetime
    kyc_status: KycStatus = KycStatus.PENDING


class Account(BaseModel):
    id: str
    account_no: str
    type: AccountType
    status: AccountStatus = AccountStatus.ACTIVE
    opened_at: datetime
    risk_score: Probability = 0.0  # own risk, from rule scores and flags
    propagated_risk: Probability = 0.0  # risk received from connected accounts
    combined_risk: Probability = 0.0  # 1 - (1 - risk_score) * (1 - propagated_risk)
    pre_emptive: bool = False  # surfaced by propagation although no rule fired
    risk_explanation: list[str] = []  # top contributing paths, human-readable
    is_flagged: bool = False
    community_id: int | None = None  # set by GDS community detection


class Device(BaseModel):
    device_id: str
    fingerprint: str
    os: str
    ip_last_seen: str | None = None


class Card(BaseModel):
    card_hash: str  # SHA-256 of the full card number
    last4: str = Field(pattern=r"^\d{4}$")
    bin: str = Field(pattern=r"^\d{6}$")  # first 6 digits: identifies the issuer
    issuer: str
    type: CardType


class Address(BaseModel):
    id: str
    line: str
    city: str
    pincode: str
    normalized_hash: str  # hash of the normalised address, used to deduplicate


class Phone(BaseModel):
    number_hash: str  # SHA-256 of the E.164 number


class Merchant(BaseModel):
    id: str
    name: str
    category: str
    mcc: str = Field(pattern=r"^\d{4}$")  # ISO 18245 merchant category code
    country: str = Field(min_length=2, max_length=2)  # ISO 3166-1 alpha-2
    risk_tier: RiskTier = RiskTier.LOW


class Transaction(BaseModel):
    id: str
    amount: float = Field(gt=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    timestamp: datetime
    channel: Channel
    location: str  # "City, CC"
    status: TransactionStatus = TransactionStatus.APPROVED
    rule_score: float = Field(default=0.0, ge=0, le=100)
    final_score: float = Field(default=0.0, ge=0, le=100)


class FraudFlag(BaseModel):
    id: str
    source: FlagSource
    reason: str
    confidence: Probability
    created_at: datetime


class Role(StrEnum):
    ADMIN = "ADMIN"
    ANALYST = "ANALYST"
    VIEWER = "VIEWER"


class Analyst(BaseModel):
    """A dashboard user. Also the target of manual FLAGGED_BY relationships."""

    id: str
    username: str
    name: str
    role: Role = Role.ANALYST
    active: bool = True


class Ring(BaseModel):
    ring_id: str
    algorithm: RingAlgorithm
    size: int = Field(ge=1)
    avg_risk: Probability = 0.0
    density: Probability = 0.0
    shared_devices: int = 0
    shared_cards: int = 0
    shared_addresses: int = 0
    shared_phones: int = 0
    total_volume: float = 0.0
    detected_at: datetime
    status: RingStatus = RingStatus.NEW


class Alert(BaseModel):
    id: str
    type: AlertType
    severity: Severity
    explanation: str
    created_at: datetime
    status: AlertStatus = AlertStatus.OPEN
    notes: list[str] = []
