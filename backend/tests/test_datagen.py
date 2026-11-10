"""Unit tests for the synthetic data generator (no database needed)."""

from collections import defaultdict
from datetime import datetime, timezone

import pytest

from app.datagen.__main__ import ground_truth
from app.datagen.generator import GenParams, generate
from app.datagen.rings import RING_SIZES

KEY = "unit-test-key-0123456789"
NOW = datetime(2026, 11, 1, tzinfo=timezone.utc)
SMALL = GenParams(users=300, accounts=400, merchants=30, transactions=3000, rings_per_type=2, seed=7)


@pytest.fixture(scope="module")
def ds():
    return generate(SMALL, KEY, now=NOW)


def test_totals_match_parameters(ds) -> None:
    assert len(ds.users) == SMALL.users
    assert len(ds.accounts) == SMALL.accounts
    assert len(ds.merchants) == SMALL.merchants
    assert len(ds.transactions) == SMALL.transactions


def test_same_seed_gives_same_data(ds) -> None:
    again = generate(SMALL, KEY, now=NOW)
    assert [(r.tx.id, r.tx.amount, r.source, r.target) for r in again.transactions] == [
        (r.tx.id, r.tx.amount, r.source, r.target) for r in ds.transactions
    ]
    other = generate(GenParams(**{**SMALL.__dict__, "seed": 8}), KEY, now=NOW)
    assert [a.id for a in other.accounts] == [a.id for a in ds.accounts]  # same IDs...
    assert [r.tx.amount for r in other.transactions] != [r.tx.amount for r in ds.transactions]


def test_every_ring_type_planted_with_valid_sizes(ds) -> None:
    by_type = defaultdict(list)
    for ring in ds.rings:
        by_type[ring["type"]].append(ring)
    assert set(by_type) == set(RING_SIZES)
    for kind, rings in by_type.items():
        assert len(rings) == SMALL.rings_per_type
        lo, hi = RING_SIZES[kind]
        assert all(lo <= len(r["accounts"]) <= hi for r in rings)


def test_ring_members_are_disjoint(ds) -> None:
    members = [a for r in ds.rings for a in r["accounts"]]
    assert len(members) == len(set(members))


def test_shared_device_rings_share_a_device(ds) -> None:
    devices_of = defaultdict(set)
    for account, device in ds.uses_device:
        devices_of[account].add(device)
    for ring in (r for r in ds.rings if r["type"] == "shared_device"):
        shared = ring["shared"]["devices"][0]
        assert all(shared in devices_of[a] for a in ring["accounts"])


def test_mule_rings_live_at_one_address(ds) -> None:
    address_of = dict(ds.lives_at)
    for ring in (r for r in ds.rings if r["type"] == "shared_address_mule"):
        assert {address_of[u] for u in ring["users"]} == {ring["shared"]["address"]}


def test_card_testing_accounts_share_cards_and_spend_tiny_amounts(ds) -> None:
    cards_of = defaultdict(set)
    for account, card in ds.uses_card:
        cards_of[account].add(card)
    for ring in (r for r in ds.rings if r["type"] == "card_testing"):
        ring_cards = set(ring["shared"]["cards"])
        assert all(len(cards_of[a] & ring_cards) >= 2 for a in ring["accounts"])
        amounts = [t.tx.amount for t in ds.transactions if t.source in ring["accounts"]]
        assert amounts and max(amounts) <= 50


def test_layering_chain_neighbours_share_a_phone_and_pass_money_along(ds) -> None:
    phones_of = defaultdict(set)
    for user, phone in ds.has_phone:
        phones_of[user].add(phone)
    hops = {(t.source, t.target) for t in ds.transactions if not t.to_merchant}
    for ring in (r for r in ds.rings if r["type"] == "layering_chain"):
        users, accounts = ring["users"], ring["accounts"]
        for i in range(len(users) - 1):
            assert phones_of[users[i]] & phones_of[users[i + 1]]
            assert (accounts[i], accounts[i + 1]) in hops


def test_flags_only_on_ring_members_and_at_least_one_per_type(ds) -> None:
    fraud = {a for r in ds.rings for a in r["accounts"]}
    flagged = {f["account"] for f in ds.flags}
    assert flagged <= fraud
    for kind in RING_SIZES:
        assert any(r["flagged_accounts"] for r in ds.rings if r["type"] == kind)
    assert all(a.is_flagged == (a.id in flagged) for a in ds.accounts)


def test_benign_sharing_exists_outside_rings(ds) -> None:
    """Some ordinary families share an address, so shared attributes alone are not proof."""
    fraud_users = {u for r in ds.rings for u in r["users"]}
    users_at = defaultdict(set)
    for user, address in ds.lives_at:
        if user not in fraud_users:
            users_at[address].add(user)
    big = generate(GenParams(seed=1, rings_per_type=1, transactions=8000), KEY, now=NOW)
    big_users_at = defaultdict(set)
    big_fraud = {u for r in big.rings for u in r["users"]}
    for user, address in big.lives_at:
        if user not in big_fraud:
            big_users_at[address].add(user)
    assert any(len(users) > 1 for users in big_users_at.values())


def test_transactions_sorted_and_not_in_future(ds) -> None:
    stamps = [r.tx.timestamp for r in ds.transactions]
    assert stamps == sorted(stamps)
    assert max(stamps) <= NOW


def test_ground_truth_lists_every_ring_account(ds) -> None:
    truth = ground_truth(ds, SMALL)
    assert truth["stats"]["rings"] == 4 * SMALL.rings_per_type
    assert len(truth["fraud_accounts"]) == truth["stats"]["ring_accounts"]


def test_too_few_users_is_rejected() -> None:
    with pytest.raises(ValueError):
        generate(GenParams(users=20, accounts=40, merchants=30, transactions=3000), KEY, now=NOW)
