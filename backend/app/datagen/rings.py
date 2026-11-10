"""Plants fraud rings with known members: the ground truth for evaluation.

Each planter creates new users and accounts wired together the way a real ring
is, gives them transactions, and returns a ground-truth record. Many ring
transactions are deliberately unremarkable on their own (normal amounts,
domestic merchants) so per-transaction rules miss them; the ring is only
visible through the shared attributes.
"""

from collections.abc import Callable
from datetime import timedelta

from app.datagen.builder import Builder
from app.models.graph import Channel, KycStatus, RiskTier, TransactionStatus

# (min, max) members per ring type.
RING_SIZES: dict[str, tuple[int, int]] = {
    "shared_device": (4, 8),
    "shared_address_mule": (5, 9),
    "card_testing": (3, 6),
    "layering_chain": (4, 7),
}


def _members(b: Builder, size: int, address_id: str | None = None) -> tuple[list[str], list[str]]:
    """New users (recently created, mostly unverified) with one account each."""
    users, accounts = [], []
    for _ in range(size):
        user = b.new_user(
            address_id=address_id,
            kyc=b.rng.choices([KycStatus.PENDING, KycStatus.VERIFIED], weights=[60, 40])[0],
            created_at=b.random_time(90, 5),
        )
        users.append(user)
        accounts.append(b.new_account(user))
    return users, accounts


def _merchants(b: Builder, tier: RiskTier) -> list[str]:
    return [m.id for m in b.ds.merchants if m.risk_tier == tier]


def shared_device(b: Builder, size: int, normal_accounts: list[str]) -> dict:
    """Synthetic identities operated from one or two handsets, cashing out at
    high-risk merchants (gift cards, crypto, money transfer)."""
    users, accounts = _members(b, size)
    devices = [b.new_device() for _ in range(b.rng.randint(1, 2))]
    for i, account in enumerate(accounts):
        b.link_device(account, devices[0])
        if len(devices) > 1 and i % 2:
            b.link_device(account, devices[1])
    high_risk = _merchants(b, RiskTier.HIGH)
    for account in accounts:
        for _ in range(b.rng.randint(3, 8)):
            b.add_tx(
                account,
                b.rng.choice(high_risk),
                to_merchant=True,
                amount=b.rng.uniform(2_000, 20_000),
                timestamp=b.random_time(7),
            )
    return {"type": "shared_device", "users": users, "accounts": accounts,
            "shared": {"devices": devices}}


def shared_address_mule(b: Builder, size: int, normal_accounts: list[str]) -> dict:
    """Money mules registered at one address. Each receives transfers from
    ordinary accounts and forwards ~90% to a collector, who cashes out."""
    address = b.new_address()
    users, accounts = _members(b, size, address_id=address)
    for account in accounts:
        b.link_device(account, b.new_device())
    collector, mules = accounts[0], accounts[1:]
    collected, last_seen = 0.0, b.now - timedelta(days=10)
    for mule in mules:
        received, last = 0.0, b.now - timedelta(days=10)
        for _ in range(b.rng.randint(2, 5)):
            amount, ts = b.rng.uniform(3_000, 15_000), b.random_time(10, 1)
            b.add_tx(b.rng.choice(normal_accounts), mule, to_merchant=False, amount=amount, timestamp=ts)
            received, last = received + amount, max(last, ts)
        forward = received * b.rng.uniform(0.85, 0.95)
        ts = last + timedelta(hours=b.rng.uniform(1, 12))
        b.add_tx(mule, collector, to_merchant=False, amount=forward, timestamp=ts)
        collected, last_seen = collected + forward, max(last_seen, ts)
    b.add_tx(
        collector,
        b.rng.choice(_merchants(b, RiskTier.HIGH)),
        to_merchant=True,
        amount=collected * 0.9,
        timestamp=last_seen + timedelta(hours=2),
    )
    return {"type": "shared_address_mule", "users": users, "accounts": accounts,
            "shared": {"address": address}}


def card_testing(b: Builder, size: int, normal_accounts: list[str]) -> dict:
    """Accounts trying a handful of stolen cards with many tiny purchases in a
    short burst; many attempts are declined."""
    users, accounts = _members(b, size)
    cards = [b.new_card() for _ in range(b.rng.randint(2, 4))]
    for account in accounts:
        b.link_device(account, b.new_device())
        for card in b.rng.sample(cards, k=b.rng.randint(2, len(cards))):
            b.link_card(account, card)
    targets = b.rng.sample(_merchants(b, RiskTier.LOW), k=3)
    burst_start = b.random_time(5, 1)
    for account in accounts:
        for _ in range(b.rng.randint(10, 25)):
            b.add_tx(
                account,
                b.rng.choice(targets),
                to_merchant=True,
                amount=b.rng.uniform(1, 50),
                timestamp=burst_start + timedelta(minutes=b.rng.uniform(0, 90)),
                channel=Channel.CARD,
                status=TransactionStatus.DECLINED if b.rng.random() < 0.4 else TransactionStatus.APPROVED,
            )
    return {"type": "card_testing", "users": users, "accounts": accounts,
            "shared": {"cards": cards}}


def layering_chain(b: Builder, size: int, normal_accounts: list[str]) -> dict:
    """A large deposit hops A0 -> A1 -> ... -> An within hours, shrinking a few
    percent each hop. Neighbouring members share a phone number."""
    users, accounts = _members(b, size)
    phones = []
    for prev, nxt in zip(users, users[1:]):
        phone = b.phone_of_user[prev]
        b.add_phone(nxt, phone)
        phones.append(phone)
    for account in accounts:
        b.link_device(account, b.new_device())
    amount, ts = b.rng.uniform(50_000, 200_000), b.random_time(5, 2)
    b.add_tx(b.rng.choice(normal_accounts), accounts[0], to_merchant=False, amount=amount, timestamp=ts)
    for src, dst in zip(accounts, accounts[1:]):
        amount *= b.rng.uniform(0.95, 0.98)
        ts += timedelta(minutes=b.rng.uniform(10, 90))
        b.add_tx(src, dst, to_merchant=False, amount=amount, timestamp=ts, channel=Channel.NETBANKING)
    return {"type": "layering_chain", "users": users, "accounts": accounts,
            "shared": {"phones": phones}}


PLANTERS: dict[str, Callable[[Builder, int, list[str]], dict]] = {
    "shared_device": shared_device,
    "shared_address_mule": shared_address_mule,
    "card_testing": card_testing,
    "layering_chain": layering_chain,
}
