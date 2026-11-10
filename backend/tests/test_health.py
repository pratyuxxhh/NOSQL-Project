"""Unit tests for /health and /ready using a fake Neo4j driver (no database needed)."""

from fastapi.testclient import TestClient

from app.db.neo4j import get_driver
from app.db.schema import load_statements, schema_object_names
from app.main import app

ALL_SCHEMA_NAMES = sorted(schema_object_names(load_statements()))


class FakeDriver:
    """Answers the readiness queries.

    Queries containing the `failing` substring raise; SHOW INDEXES returns
    `index_names` (all schema objects by default).
    """

    def __init__(self, failing: str | None = None, index_names: list[str] | None = None) -> None:
        self.failing = failing
        self.index_names = ALL_SCHEMA_NAMES if index_names is None else index_names

    async def execute_query(self, query: str):
        if self.failing and self.failing in query:
            raise RuntimeError(f"{self.failing} unavailable")
        if query.startswith("SHOW INDEXES"):
            return [{"names": self.index_names}], None, None
        return [{"version": "test"}], None, None


def client_with(driver: FakeDriver) -> TestClient:
    app.dependency_overrides[get_driver] = lambda: driver
    return TestClient(app)


def teardown_function() -> None:
    app.dependency_overrides.clear()


def test_health_needs_no_database() -> None:
    response = TestClient(app).get("/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_when_everything_available() -> None:
    response = client_with(FakeDriver()).get("/ready")
    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ready"
    assert set(body["checks"]) == {"neo4j", "gds", "apoc", "schema"}


def test_not_ready_when_gds_missing() -> None:
    response = client_with(FakeDriver(failing="gds")).get("/ready")
    assert response.status_code == 503
    body = response.json()
    assert body["checks"]["gds"]["ok"] is False
    assert body["checks"]["apoc"]["ok"] is True


def test_not_ready_when_schema_incomplete() -> None:
    names = [n for n in ALL_SCHEMA_NAMES if n != "transaction_id"]
    response = client_with(FakeDriver(index_names=names)).get("/ready")
    assert response.status_code == 503
    schema = response.json()["checks"]["schema"]
    assert schema["ok"] is False
    assert "transaction_id" in schema["error"]


def test_not_ready_when_neo4j_down_skips_other_checks() -> None:
    response = client_with(FakeDriver(failing="dbms.components")).get("/ready")
    assert response.status_code == 503
    assert set(response.json()["checks"]) == {"neo4j"}
