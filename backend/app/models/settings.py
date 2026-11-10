"""Runtime-tunable settings (rules, propagation, detection, decisions).

Defaults for the rules come from rules.yaml; admins can change everything at
runtime from the Admin page, and changes are stored in Neo4j (a :Config node).
"""

from pathlib import Path

import yaml
from pydantic import BaseModel, Field

from app.models.graph import RingAlgorithm

RULES_PATH = Path(__file__).resolve().parents[2] / "rules.yaml"


class RuleSettings(BaseModel):
    high_amount_threshold: float = Field(50000, gt=0)
    high_amount_points: int = Field(40, ge=0, le=100)
    velocity_max: int = Field(5, ge=1)
    velocity_window_minutes: int = Field(10, ge=1)
    velocity_points: int = Field(30, ge=0, le=100)
    new_device_points: int = Field(15, ge=0, le=100)
    unusual_location_points: int = Field(25, ge=0, le=100)
    high_risk_merchant_points: int = Field(30, ge=0, le=100)
    flag_threshold: int = Field(60, ge=1, le=100)

    @classmethod
    def from_yaml(cls, path: Path = RULES_PATH) -> "RuleSettings":
        return cls(**yaml.safe_load(path.read_text(encoding="utf-8")))


class PropagationSettings(BaseModel):
    # How strongly each relationship type carries risk (0-1).
    weights: dict[str, float] = {
        "SHARED_DEVICE": 0.9,
        "SHARED_CARD": 0.9,
        "SHARED_PHONE": 0.8,
        "SHARED_ADDRESS": 0.6,
        "TRANSACTED_WITH": 0.4,
    }
    decay: float = Field(0.5, gt=0, le=1)  # multiplied in once per hop
    max_depth: int = Field(3, ge=1, le=5)
    surface_threshold: float = Field(0.3, gt=0, le=1)  # propagated risk that puts an account up for review


class DetectionSettings(BaseModel):
    algorithm: RingAlgorithm = RingAlgorithm.LOUVAIN
    interval_seconds: int = Field(60, ge=10)
    min_ring_size: int = Field(3, ge=2)
    max_ring_size: int = Field(30, ge=3)
    density_threshold: float = Field(0.5, gt=0, le=1)
    new_account_days: int = Field(90, ge=1)  # an account opened within this many days is "new"
    min_new_account_ratio: float = Field(0.5, ge=0, le=1)  # dense clusters need this share of new accounts


class DecisionSettings(BaseModel):
    review_threshold: float = Field(40, ge=0, le=100)  # final_score >= this -> REVIEW
    block_threshold: float = Field(70, ge=0, le=100)  # final_score >= this -> BLOCK


class RuntimeSettings(BaseModel):
    rules: RuleSettings = Field(default_factory=RuleSettings.from_yaml)
    propagation: PropagationSettings = Field(default_factory=PropagationSettings)
    detection: DetectionSettings = Field(default_factory=DetectionSettings)
    decision: DecisionSettings = Field(default_factory=DecisionSettings)
