"""Request/response schemas for transaction ingestion and scoring (F2, F13)."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field, model_validator

from app.models.graph import AccountType, CardType, Channel, KycStatus, RiskTier, TransactionStatus


class AddressIn(BaseModel):
    line: str = Field(min_length=1, max_length=200)
    city: str = Field(min_length=1, max_length=80)
    pincode: str = Field(pattern=r"^\d{6}$")


class UserIn(BaseModel):
    """Account holder details. Needed the first time an account is seen."""

    id: str = Field(min_length=1, max_length=64)
    name: str = Field(min_length=1, max_length=120)
    email: str = Field(max_length=200)
    phone: str = Field(min_length=7, max_length=20)  # raw; hashed + masked on arrival
    kyc_status: KycStatus = KycStatus.PENDING
    address: AddressIn


class AccountIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    account_no: str | None = Field(default=None, max_length=34)
    type: AccountType = AccountType.SAVINGS
    opened_at: datetime | None = None


class DeviceIn(BaseModel):
    device_id: str = Field(min_length=1, max_length=128)
    fingerprint: str | None = Field(default=None, max_length=256)
    os: str | None = Field(default=None, max_length=64)
    ip: str | None = Field(default=None, max_length=45)


class CardIn(BaseModel):
    """The raw number is hashed immediately and never stored or logged."""

    number: str = Field(pattern=r"^[\d \-]{12,23}$")
    issuer: str | None = None
    type: CardType = CardType.DEBIT


class MerchantIn(BaseModel):
    id: str = Field(min_length=1, max_length=64)
    name: str | None = None
    category: str | None = None
    mcc: str | None = Field(default=None, pattern=r"^\d{4}$")
    country: str = Field(default="IN", min_length=2, max_length=2)
    risk_tier: RiskTier = RiskTier.LOW


class TransactionEvent(BaseModel):
    """One transaction from a transaction-processing service. Pay either a
    merchant or another account (`counterparty_account_id`)."""

    transaction_id: str = Field(min_length=1, max_length=64)
    timestamp: datetime
    amount: float = Field(gt=0, le=100_000_000)
    currency: str = Field(default="INR", min_length=3, max_length=3)
    channel: Channel
    location: str = Field(pattern=r"^[^,]{1,80},\s?[A-Za-z]{2}$")  # "City, CC"
    status: TransactionStatus = TransactionStatus.APPROVED
    account: AccountIn
    user: UserIn | None = None
    device: DeviceIn | None = None
    card: CardIn | None = None
    merchant: MerchantIn | None = None
    counterparty_account_id: str | None = Field(default=None, max_length=64)

    @model_validator(mode="after")
    def one_payee(self) -> "TransactionEvent":
        if (self.merchant is None) == (self.counterparty_account_id is None):
            raise ValueError("provide exactly one of merchant or counterparty_account_id")
        return self


class BatchIn(BaseModel):
    events: list[TransactionEvent] = Field(min_length=1, max_length=1000)


class Decision(StrEnum):
    ALLOW = "ALLOW"
    REVIEW = "REVIEW"
    BLOCK = "BLOCK"


class ScoreResult(BaseModel):
    transaction_id: str
    account_id: str
    decision: Decision
    final_score: float
    rule_score: int
    rule_reasons: list[str]
    account_risk: float  # graph risk, 0-1: 1.0 if flagged, else propagated risk
    propagated_risk: float
    risk_explanation: list[str]
    linked_to_fraud: bool
    ring_ids: list[str]
    duplicate: bool = False  # transaction ID seen before; stored result returned
    latency_ms: float
