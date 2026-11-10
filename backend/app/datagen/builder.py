"""Building blocks for synthetic data.

The Builder creates validated nodes (via the Pydantic models in app.models.graph)
and records relationships, so everything it produces matches the data model.
"""

import random
from dataclasses import dataclass, field
from datetime import datetime, timedelta

from faker import Faker

from app.models.graph import (
    Account,
    AccountType,
    Address,
    Card,
    CardType,
    Channel,
    Device,
    KycStatus,
    Merchant,
    Phone,
    Transaction,
    TransactionStatus,
    User,
)
from app.security import pii

# (issuer, 6-digit BIN)
CARD_ISSUERS = [
    ("HDFC Bank", "485498"),
    ("ICICI Bank", "524193"),
    ("State Bank of India", "652150"),
    ("Axis Bank", "471865"),
    ("Kotak Mahindra Bank", "416021"),
]
DEVICE_OS = ["Android 14", "Android 13", "iOS 17", "iOS 18", "Windows 11", "macOS 14"]


@dataclass
class TxRecord:
    tx: Transaction
    source: str  # account id
    target: str  # merchant id or account id
    to_merchant: bool


@dataclass
class Dataset:
    merchants: list[Merchant] = field(default_factory=list)
    users: list[User] = field(default_factory=list)
    addresses: dict[str, Address] = field(default_factory=dict)  # by id
    phones: dict[str, Phone] = field(default_factory=dict)  # by number_hash
    accounts: list[Account] = field(default_factory=list)
    devices: dict[str, Device] = field(default_factory=dict)  # by device_id
    cards: dict[str, Card] = field(default_factory=dict)  # by card_hash
    transactions: list[TxRecord] = field(default_factory=list)
    lives_at: list[tuple[str, str]] = field(default_factory=list)  # (user_id, address_id)
    has_phone: list[tuple[str, str]] = field(default_factory=list)  # (user_id, number_hash)
    owns: list[tuple[str, str]] = field(default_factory=list)  # (user_id, account_id)
    uses_device: list[tuple[str, str]] = field(default_factory=list)  # (account_id, device_id)
    uses_card: list[tuple[str, str]] = field(default_factory=list)  # (account_id, card_hash)
    flags: list[dict] = field(default_factory=list)  # {account, reason, at, confidence}
    rings: list[dict] = field(default_factory=list)  # ground truth


class Builder:
    def __init__(self, seed: int, now: datetime, pii_key: str) -> None:
        self.rng = random.Random(seed)
        self.fake = Faker("en_IN")
        self.fake.seed_instance(seed)
        self.now = now
        self.key = pii_key
        self.ds = Dataset()
        self._counters: dict[str, int] = {}
        self._address_by_hash: dict[str, str] = {}
        self.users_by_id: dict[str, User] = {}
        self.accounts_by_id: dict[str, Account] = {}
        self.address_of_user: dict[str, str] = {}
        self.phone_of_user: dict[str, str] = {}  # user_id -> number_hash
        self.owner_of: dict[str, str] = {}  # account_id -> user_id

    def _next_id(self, prefix: str, width: int = 6) -> str:
        n = self._counters.get(prefix, 0) + 1
        self._counters[prefix] = n
        return f"{prefix}{n:0{width}d}"

    def random_time(self, max_days_ago: float, min_days_ago: float = 0) -> datetime:
        """A random moment between `max_days_ago` and `min_days_ago` days before now."""
        seconds = self.rng.uniform(min_days_ago * 86400, max_days_ago * 86400)
        return self.now - timedelta(seconds=seconds)

    def city_of_account(self, account_id: str) -> str:
        address_id = self.address_of_user[self.owner_of[account_id]]
        return self.ds.addresses[address_id].city

    # --- identity -------------------------------------------------------------

    def new_address(self) -> str:
        line = self.fake.street_address().replace("\n", ", ")
        city = self.fake.city()
        pincode = self.fake.postcode()
        normalized_hash = pii.hash_address(line, city, pincode, self.key)
        if normalized_hash in self._address_by_hash:  # same address generated twice
            return self._address_by_hash[normalized_hash]
        address_id = self._next_id("ADDR")
        self.ds.addresses[address_id] = Address(
            id=address_id, line=line, city=city, pincode=pincode, normalized_hash=normalized_hash
        )
        self._address_by_hash[normalized_hash] = address_id
        return address_id

    def new_user(
        self,
        address_id: str | None = None,
        kyc: KycStatus | None = None,
        created_at: datetime | None = None,
    ) -> str:
        user_id = self._next_id("U")
        address_id = address_id or self.new_address()
        phone = f"+91{self.rng.randint(6, 9)}{self.rng.randint(0, 10**9 - 1):09d}"
        number_hash = pii.hash_phone(phone, self.key)
        self.ds.phones.setdefault(number_hash, Phone(number_hash=number_hash))
        user = User(
            id=user_id,
            name=self.fake.name(),
            email=self.fake.email(),
            phone=pii.mask_phone(phone),
            created_at=created_at or self.random_time(3 * 365, 30),
            kyc_status=kyc
            or self.rng.choices(
                [KycStatus.VERIFIED, KycStatus.PENDING, KycStatus.REJECTED], weights=[90, 8, 2]
            )[0],
        )
        self.ds.users.append(user)
        self.users_by_id[user_id] = user
        self.address_of_user[user_id] = address_id
        self.phone_of_user[user_id] = number_hash
        self.ds.lives_at.append((user_id, address_id))
        self.ds.has_phone.append((user_id, number_hash))
        return user_id

    def add_phone(self, user_id: str, number_hash: str) -> None:
        """Register an existing phone number to another user as well."""
        self.ds.has_phone.append((user_id, number_hash))

    def new_account(self, user_id: str, opened_at: datetime | None = None) -> str:
        account_id = self._next_id("A")
        created = self.users_by_id[user_id].created_at
        account = Account(
            id=account_id,
            account_no=f"50{self._counters['A']:010d}",
            type=self.rng.choices(
                [AccountType.SAVINGS, AccountType.CURRENT, AccountType.WALLET, AccountType.CREDIT],
                weights=[60, 15, 20, 5],
            )[0],
            opened_at=opened_at or created + (self.now - created) * self.rng.random() * 0.5,
        )
        self.ds.accounts.append(account)
        self.accounts_by_id[account_id] = account
        self.owner_of[account_id] = user_id
        self.ds.owns.append((user_id, account_id))
        return account_id

    # --- attributes -----------------------------------------------------------

    def new_device(self) -> str:
        device_id = self._next_id("D")
        self.ds.devices[device_id] = Device(
            device_id=device_id,
            fingerprint=f"{self.rng.getrandbits(64):016x}",
            os=self.rng.choice(DEVICE_OS),
            ip_last_seen=self.fake.ipv4_public(),
        )
        return device_id

    def link_device(self, account_id: str, device_id: str) -> None:
        self.ds.uses_device.append((account_id, device_id))

    def new_card(self) -> str:
        issuer, bin_ = self.rng.choice(CARD_ISSUERS)
        number = bin_ + f"{self.rng.randint(0, 10**10 - 1):010d}"
        card_hash = pii.hash_card(number, self.key)
        self.ds.cards[card_hash] = Card(
            card_hash=card_hash,
            last4=number[-4:],
            bin=bin_,
            issuer=issuer,
            type=self.rng.choice(list(CardType)),
        )
        return card_hash

    def link_card(self, account_id: str, card_hash: str) -> None:
        self.ds.uses_card.append((account_id, card_hash))

    # --- activity -------------------------------------------------------------

    def add_tx(
        self,
        source: str,
        target: str,
        *,
        to_merchant: bool,
        amount: float,
        timestamp: datetime,
        channel: Channel | None = None,
        status: TransactionStatus = TransactionStatus.APPROVED,
        location: str | None = None,
    ) -> str:
        tx_id = self._next_id("T", 7)
        if channel is None:
            options = (
                [Channel.CARD, Channel.UPI, Channel.WALLET, Channel.NETBANKING]
                if to_merchant
                else [Channel.UPI, Channel.NETBANKING]
            )
            channel = self.rng.choice(options)
        tx = Transaction(
            id=tx_id,
            amount=round(max(amount, 1.0), 2),
            timestamp=min(timestamp, self.now),
            channel=channel,
            location=location or f"{self.city_of_account(source)}, IN",
            status=status,
        )
        self.ds.transactions.append(TxRecord(tx, source, target, to_merchant))
        return tx_id

    def flag(self, account_id: str, reason: str, at: datetime, confidence: float = 0.95) -> None:
        """Mark an account as known fraud (flagged by an analyst)."""
        account = self.accounts_by_id[account_id]
        account.is_flagged = True
        account.risk_score = 1.0
        self.ds.flags.append(
            {"account": account_id, "reason": reason, "at": at, "confidence": confidence}
        )
