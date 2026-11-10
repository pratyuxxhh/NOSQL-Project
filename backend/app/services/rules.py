"""Baseline rule-based scoring (F3): every transaction judged in isolation.

This is deliberately the "existing methodology". It looks only at the
transaction and its own account's recent activity, never at the network, so
the dashboard can show what it misses compared with graph detection.
"""

from dataclasses import dataclass

from app.models.graph import RiskTier
from app.models.settings import RuleSettings


@dataclass(frozen=True)
class RuleContext:
    amount: float
    recent_count: int  # this account's transactions in the velocity window, including this one
    new_device: bool
    location: str  # "City, CC"
    merchant_tier: RiskTier | None  # None for account-to-account transfers


def is_unusual_location(location: str, home_country: str = "IN") -> bool:
    """Outside the customer's home country (all customers are Indian in this system)."""
    _, _, country = location.rpartition(",")
    return country.strip().upper() != home_country


def score(ctx: RuleContext, rules: RuleSettings) -> tuple[int, list[str]]:
    """Return (rule_score 0-100, human-readable reasons)."""
    points, reasons = 0, []
    if ctx.amount >= rules.high_amount_threshold:
        points += rules.high_amount_points
        reasons.append(f"High amount (>= {rules.high_amount_threshold:,.0f})")
    if ctx.recent_count > rules.velocity_max:
        points += rules.velocity_points
        reasons.append(
            f"Velocity: {ctx.recent_count} transactions in {rules.velocity_window_minutes} min"
        )
    if ctx.new_device:
        points += rules.new_device_points
        reasons.append("New device for this account")
    if is_unusual_location(ctx.location):
        points += rules.unusual_location_points
        reasons.append(f"Unusual location: {ctx.location}")
    if ctx.merchant_tier == RiskTier.HIGH:
        points += rules.high_risk_merchant_points
        reasons.append("High-risk merchant category")
    return min(points, 100), reasons
