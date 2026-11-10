"""Unit tests for the graph data model's validation rules."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.models.graph import (
    Account,
    AccountType,
    Card,
    CardType,
    Channel,
    RelType,
    SHARED_RELATIONSHIPS,
    Transaction,
)

NOW = datetime.now(timezone.utc)


def test_synopsis_relationships_are_defined() -> None:
    for name in ("TRANSACTED_WITH", "SHARED_DEVICE", "SHARED_ADDRESS", "FLAGGED_BY"):
        assert RelType(name)


def test_every_shared_relationship_has_a_source_attribute() -> None:
    assert set(SHARED_RELATIONSHIPS) == {
        RelType.SHARED_DEVICE,
        RelType.SHARED_CARD,
        RelType.SHARED_ADDRESS,
        RelType.SHARED_PHONE,
    }


def test_account_defaults_are_unflagged_and_zero_risk() -> None:
    account = Account(id="A1", account_no="0001", type=AccountType.SAVINGS, opened_at=NOW)
    assert account.risk_score == 0.0
    assert account.propagated_risk == 0.0
    assert account.is_flagged is False
    assert account.community_id is None


@pytest.mark.parametrize("value", [-0.1, 1.5])
def test_account_risk_must_be_a_probability(value: float) -> None:
    with pytest.raises(ValidationError):
        Account(
            id="A1", account_no="0001", type=AccountType.SAVINGS, opened_at=NOW, risk_score=value
        )


def test_card_rejects_anything_but_last_four_digits() -> None:
    with pytest.raises(ValidationError):
        Card(card_hash="h", last4="4111111111111111", bin="411111", issuer="X", type=CardType.DEBIT)


def test_transaction_scores_are_0_to_100_and_amount_positive() -> None:
    base = dict(id="T1", timestamp=NOW, channel=Channel.UPI, location="Bengaluru, IN")
    assert Transaction(amount=10, rule_score=100, **base).currency == "INR"
    with pytest.raises(ValidationError):
        Transaction(amount=10, rule_score=101, **base)
    with pytest.raises(ValidationError):
        Transaction(amount=0, **base)
