"""Unit tests for ingestion event validation and bulk rule scoring."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.datagen.generator import GenParams, generate
from app.datagen.scoring import score_dataset
from app.models.events import TransactionEvent
from app.models.settings import RuleSettings

BASE = {
    "transaction_id": "T1",
    "timestamp": "2026-11-10T10:00:00Z",
    "amount": 100,
    "channel": "UPI",
    "location": "Pune, IN",
    "account": {"id": "A1"},
}


def test_needs_exactly_one_payee() -> None:
    TransactionEvent(**BASE, merchant={"id": "M1"})
    TransactionEvent(**BASE, counterparty_account_id="A2")
    with pytest.raises(ValidationError):
        TransactionEvent(**BASE)
    with pytest.raises(ValidationError):
        TransactionEvent(**BASE, merchant={"id": "M1"}, counterparty_account_id="A2")


@pytest.mark.parametrize("field, value", [("amount", 0), ("location", "Pune"), ("channel", "FAX")])
def test_invalid_fields_rejected(field, value) -> None:
    with pytest.raises(ValidationError):
        TransactionEvent(**{**BASE, field: value, "merchant": {"id": "M1"}})


def test_card_number_format_checked() -> None:
    with pytest.raises(ValidationError):
        TransactionEvent(**BASE, merchant={"id": "M1"}, card={"number": "not-a-card"})


def test_bulk_scoring_catches_card_testing_velocity() -> None:
    ds = generate(GenParams(users=300, accounts=400, merchants=30, transactions=3000, rings_per_type=2),
                  "unit-test-key-0123456789", now=datetime(2026, 11, 1, tzinfo=timezone.utc))
    rows, account_risk = score_dataset(ds, RuleSettings())
    assert len(rows) == len(ds.transactions)
    by_id = {r["id"]: r for r in rows}
    card_ring = next(r for r in ds.rings if r["type"] == "card_testing")
    ring_tx = [t.tx.id for t in ds.transactions if t.source in card_ring["accounts"]]
    assert any("Velocity" in " ".join(by_id[t]["reasons"]) for t in ring_tx)
    assert all(0 <= v <= 1 for v in account_risk.values())
