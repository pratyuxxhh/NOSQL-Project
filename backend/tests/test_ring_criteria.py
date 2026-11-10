"""Unit tests for ring suspicion criteria and ring metrics."""

from app.models.settings import DetectionSettings
from app.services.ring_detection import is_suspicious, overlaps, ring_id_for, ring_metrics

DET = DetectionSettings()


def edge(a: str, b: str, type_: str = "SHARED_DEVICE", key: str = "D1") -> dict:
    return {"a": a, "b": b, "type": type_, "key": key}


def test_density_of_a_triangle_is_one() -> None:
    m = ring_metrics(["A", "B", "C"], [edge("A", "B"), edge("A", "C"), edge("B", "C")])
    assert m["density"] == 1.0 and m["shared_devices"] == 1


def test_density_counts_pairs_not_parallel_edges() -> None:
    edges = [edge("A", "B", key="D1"), edge("A", "B", key="D2"), edge("B", "C", "SHARED_CARD", "C1")]
    m = ring_metrics(["A", "B", "C", "D"], edges)
    assert m["density"] == round(2 / 6, 4)
    assert m["shared_devices"] == 2 and m["shared_cards"] == 1


def test_too_small_is_never_a_ring() -> None:
    assert not is_suspicious(2, 1.0, 1, 1.0, DET)


def test_known_fraud_inside_makes_a_ring() -> None:
    assert is_suspicious(5, 0.1, 1, 0.0, DET)


def test_dense_new_accounts_make_a_ring() -> None:
    assert is_suspicious(4, 0.8, 0, 0.75, DET)


def test_dense_old_household_is_not_a_ring() -> None:
    assert not is_suspicious(4, 1.0, 0, 0.0, DET)


def test_sparse_new_accounts_are_not_a_ring() -> None:
    assert not is_suspicious(6, 0.2, 0, 1.0, DET)


def test_ring_id_is_stable_and_order_independent() -> None:
    assert ring_id_for(["B", "A", "C"]) == ring_id_for(["A", "B", "C"])
    assert ring_id_for(["A", "B"]) != ring_id_for(["A", "C"])


def test_overlap() -> None:
    assert overlaps(["A", "B", "C", "D"], ["A", "B"])
    assert not overlaps(["A", "B", "C", "D"], ["A", "X", "Y"])
    assert not overlaps([], ["A"])
