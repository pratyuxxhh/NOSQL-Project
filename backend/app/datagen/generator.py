"""Generates a full synthetic dataset: ordinary customers, planted fraud rings
and the transactions between them.

Generation is deterministic for a given seed (and `now`), so evaluation results
are reproducible.
"""

from dataclasses import dataclass
from datetime import datetime, timezone

from app.datagen.builder import Builder, Dataset
from app.datagen.rings import PLANTERS, RING_SIZES
from app.models.graph import Merchant, RiskTier, TransactionStatus

# (category, MCC, risk tier). MCCs follow ISO 18245.
MERCHANT_CATEGORIES = [
    ("Grocery", "5411", RiskTier.LOW),
    ("Restaurants", "5812", RiskTier.LOW),
    ("Fuel", "5541", RiskTier.LOW),
    ("Pharmacy", "5912", RiskTier.LOW),
    ("Clothing", "5651", RiskTier.LOW),
    ("Telecom recharge", "4814", RiskTier.LOW),
    ("Online marketplace", "5399", RiskTier.LOW),
    ("Electronics", "5732", RiskTier.MEDIUM),
    ("Jewellery", "5944", RiskTier.MEDIUM),
    ("Airlines", "4511", RiskTier.MEDIUM),
    ("Gift cards", "5947", RiskTier.HIGH),
    ("Money transfer", "4829", RiskTier.HIGH),
    ("Crypto exchange", "6051", RiskTier.HIGH),
    ("Online gambling", "7995", RiskTier.HIGH),
]
FOREIGN_CITIES = {"AE": "Dubai", "SG": "Singapore", "GB": "London", "US": "New York"}
# How often ordinary customers pick a merchant of each tier.
TIER_WEIGHTS = {RiskTier.LOW: 1.0, RiskTier.MEDIUM: 0.4, RiskTier.HIGH: 0.05}


@dataclass(frozen=True)
class GenParams:
    users: int = 5000
    accounts: int = 7000
    merchants: int = 300
    transactions: int = 50000
    rings_per_type: int = 6
    days: int = 30  # transaction history window
    seed: int = 42
    household_rate: float = 0.03  # chance a customer shares an address with an earlier one
    shared_device_rate: float = 0.02  # chance an account uses another customer's device


def generate(params: GenParams, pii_key: str, now: datetime | None = None) -> Dataset:
    now = now or datetime.now(timezone.utc).replace(second=0, microsecond=0)
    b = Builder(params.seed, now, pii_key)

    # Decide ring sizes first so the totals come out exactly as requested.
    ring_sizes = {
        kind: [b.rng.randint(*RING_SIZES[kind]) for _ in range(params.rings_per_type)]
        for kind in PLANTERS
    }
    ring_people = sum(sum(sizes) for sizes in ring_sizes.values())
    normal_users = params.users - ring_people
    normal_accounts = params.accounts - ring_people
    if normal_users < 2 or normal_accounts < normal_users:
        raise ValueError(
            f"Need more users/accounts: rings use {ring_people} of each, and every "
            "ordinary user needs at least one account."
        )
    if params.merchants < len(MERCHANT_CATEGORIES):
        raise ValueError(f"Need at least {len(MERCHANT_CATEGORIES)} merchants (one per category).")

    _merchants(b, params.merchants)
    accounts = _population(b, normal_users, normal_accounts, params)
    _plant_rings(b, ring_sizes, accounts)

    remaining = params.transactions - len(b.ds.transactions)
    if remaining < 0:
        raise ValueError("Ring activity alone exceeds the requested transaction count.")
    _normal_transactions(b, accounts, remaining, params.days)
    b.ds.transactions.sort(key=lambda record: record.tx.timestamp)
    return b.ds


def _merchants(b: Builder, count: int) -> None:
    for i in range(count):
        category, mcc, tier = MERCHANT_CATEGORIES[i % len(MERCHANT_CATEGORIES)]
        country = "IN" if b.rng.random() < 0.95 else b.rng.choice(list(FOREIGN_CITIES))
        b.ds.merchants.append(
            Merchant(
                id=f"M{i + 1:05d}",
                name=b.fake.company(),
                category=category,
                mcc=mcc,
                country=country,
                risk_tier=tier,
            )
        )


def _population(b: Builder, n_users: int, n_accounts: int, params: GenParams) -> list[str]:
    """Ordinary customers, with a little benign sharing (families sharing an
    address or a tablet) so that not every shared attribute means fraud."""
    users: list[str] = []
    for _ in range(n_users):
        address = None
        if users and b.rng.random() < params.household_rate:
            address = b.address_of_user[b.rng.choice(users)]
        users.append(b.new_user(address_id=address))

    owners = users + [b.rng.choice(users) for _ in range(n_accounts - n_users)]
    device_of_user: dict[str, str] = {}
    accounts = []
    for owner in owners:
        account = b.new_account(owner)
        accounts.append(account)
        if owner in device_of_user and b.rng.random() < 0.8:
            device = device_of_user[owner]  # same person, same phone
        elif b.ds.uses_device and b.rng.random() < params.shared_device_rate:
            device = b.rng.choice(b.ds.uses_device)[1]  # family / shared device
        else:
            device = b.new_device()
        device_of_user.setdefault(owner, device)
        b.link_device(account, device)
        if b.rng.random() < 0.8:
            b.link_card(account, b.new_card())
    return accounts


def _plant_rings(b: Builder, ring_sizes: dict[str, list[int]], accounts: list[str]) -> None:
    for kind, sizes in ring_sizes.items():
        for n, size in enumerate(sizes, start=1):
            record = PLANTERS[kind](b, size, accounts)
            record["ring_id"] = f"GT-{kind}-{n:02d}"
            # Some rings already have one member caught (a historical chargeback):
            # the starting point for risk propagation. At least one per type.
            record["flagged_accounts"] = []
            if n == 1 or b.rng.random() < 0.5:
                member = b.rng.choice(record["accounts"])
                b.flag(member, "Confirmed chargeback (historical)", at=b.random_time(30, 8))
                record["flagged_accounts"].append(member)
            b.ds.rings.append(record)


def _normal_transactions(b: Builder, accounts: list[str], count: int, days: int) -> None:
    merchants = b.ds.merchants
    weights = [TIER_WEIGHTS[m.risk_tier] for m in merchants]
    for _ in range(count):
        source = b.rng.choice(accounts)
        # Log-normal amounts: median about Rs 1,100, with a long tail of big purchases.
        amount = min(b.rng.lognormvariate(7.0, 1.1), 500_000)
        status = TransactionStatus.DECLINED if b.rng.random() < 0.03 else TransactionStatus.APPROVED
        if b.rng.random() < 0.85:
            merchant = b.rng.choices(merchants, weights=weights)[0]
            location = (
                None if merchant.country == "IN"
                else f"{FOREIGN_CITIES[merchant.country]}, {merchant.country}"
            )
            b.add_tx(source, merchant.id, to_merchant=True, amount=amount,
                     timestamp=b.random_time(days), status=status, location=location)
        else:
            target = b.rng.choice(accounts)
            while target == source:
                target = b.rng.choice(accounts)
            b.add_tx(source, target, to_merchant=False, amount=amount,
                     timestamp=b.random_time(days), status=status)
