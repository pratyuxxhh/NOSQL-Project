"""Unit tests for the baseline rules and the final score / decision."""

import pytest

from app.models.events import Decision
from app.models.graph import RiskTier
from app.models.settings import RuleSettings, RuntimeSettings
from app.services.ingestion import decide, final_score
from app.services.rules import RuleContext, is_unusual_location, score

RULES = RuleSettings()
QUIET = RuleContext(amount=500, recent_count=1, new_device=False, location="Pune, IN",
                    merchant_tier=RiskTier.LOW)


def ctx(**changes) -> RuleContext:
    return RuleContext(**{**QUIET.__dict__, **changes})


def test_ordinary_transaction_scores_zero() -> None:
    assert score(QUIET, RULES) == (0, [])


@pytest.mark.parametrize(
    "change, points",
    [
        ({"amount": 50_000}, RULES.high_amount_points),
        ({"recent_count": RULES.velocity_max + 1}, RULES.velocity_points),
        ({"new_device": True}, RULES.new_device_points),
        ({"location": "Dubai, AE"}, RULES.unusual_location_points),
        ({"merchant_tier": RiskTier.HIGH}, RULES.high_risk_merchant_points),
    ],
)
def test_each_rule_adds_its_points(change, points) -> None:
    value, reasons = score(ctx(**change), RULES)
    assert value == points and len(reasons) == 1


def test_velocity_threshold_is_exclusive() -> None:
    assert score(ctx(recent_count=RULES.velocity_max), RULES)[0] == 0


def test_score_is_capped_at_100() -> None:
    worst = ctx(amount=10**6, recent_count=50, new_device=True, location="Dubai, AE", merchant_tier=RiskTier.HIGH)
    assert score(worst, RULES)[0] == 100


def test_rules_file_loads() -> None:
    assert RuleSettings.from_yaml().flag_threshold == 60


@pytest.mark.parametrize(
    "location, unusual", [("Pune, IN", False), ("Delhi, in", False), ("London, GB", True), ("Dubai, AE", True)]
)
def test_unusual_location(location, unusual) -> None:
    assert is_unusual_location(location) is unusual


def test_final_score_combines_rule_and_graph_risk() -> None:
    assert final_score(0, 0) == 0
    assert final_score(50, 0) == 50
    assert final_score(0, 0.5) == 50
    assert final_score(50, 0.5) == 75  # 100 * (1 - 0.5 * 0.5)


def test_decision_thresholds() -> None:
    settings = RuntimeSettings()
    assert decide(39.9, settings) == Decision.ALLOW
    assert decide(40, settings) == Decision.REVIEW
    assert decide(70, settings) == Decision.BLOCK
