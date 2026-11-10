"""Unit tests for the risk propagation maths (docs/algorithms.md worked example)."""

import pytest

from app.models.settings import PropagationSettings
from app.services.propagation import PathHit, aggregate, combined, contribution, noisy_or

SETTINGS = PropagationSettings()


def hit(source: str, target: str, *types: str, risk: float = 1.0) -> PathHit:
    nodes = (source,) + tuple(f"X{i}" for i in range(len(types) - 1)) + (target,)
    return PathHit(source, risk, target, types, nodes)


def test_worked_example_three_hops() -> None:
    # A (flagged, risk 1.0) -SHARED_DEVICE- B -SHARED_ADDRESS- C -TRANSACTED_WITH- D
    assert contribution(hit("A", "B", "SHARED_DEVICE"), SETTINGS) == pytest.approx(0.45)
    assert contribution(hit("A", "C", "SHARED_DEVICE", "SHARED_ADDRESS"), SETTINGS) == pytest.approx(0.135)
    assert contribution(
        hit("A", "D", "SHARED_DEVICE", "SHARED_ADDRESS", "TRANSACTED_WITH"), SETTINGS
    ) == pytest.approx(0.027)


def test_source_risk_scales_contribution() -> None:
    assert contribution(hit("A", "B", "SHARED_DEVICE", risk=0.5), SETTINGS) == pytest.approx(0.225)


def test_noisy_or() -> None:
    assert noisy_or([0.45, 0.30]) == pytest.approx(0.615)
    assert noisy_or([]) == 0.0
    assert noisy_or([1.0, 0.5]) == 1.0


def test_independent_sources_combine_but_parallel_paths_from_one_source_do_not() -> None:
    hits = [
        hit("A", "B", "SHARED_DEVICE"),  # 0.45
        hit("A", "B", "SHARED_CARD"),  # 0.45 again from the SAME source: ignored
        hit("E", "B", "SHARED_PHONE"),  # 0.40 from a different source
    ]
    risk, explanation = aggregate(hits, SETTINGS)["B"]
    assert risk == pytest.approx(1 - 0.55 * 0.60, abs=1e-4)
    assert len(explanation) == 2
    assert explanation[0].startswith("A -SHARED_DEVICE- B")


def test_source_does_not_propagate_to_itself() -> None:
    assert "A" not in aggregate([hit("A", "A", "SHARED_DEVICE")], SETTINGS)


def test_unknown_relationship_type_carries_no_risk() -> None:
    assert contribution(hit("A", "B", "OWNS"), SETTINGS) == 0


def test_combined_risk() -> None:
    assert combined(0.0, 0.45) == pytest.approx(0.45)
    assert combined(0.5, 0.5) == pytest.approx(0.75)
