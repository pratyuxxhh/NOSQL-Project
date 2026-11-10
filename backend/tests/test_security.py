"""Unit tests for authentication, RBAC, API keys and rate limiting."""

from datetime import datetime, timedelta, timezone

import jwt as pyjwt
import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.main import app
from app.models.graph import Role
from app.security.api_keys import generate_key, hash_key
from app.security.jwt import TokenError, create_token, decode_token
from app.security.passwords import hash_password, verify_password
from app.security.rate_limit import SlidingWindow
from app.security.rbac import has_role

SETTINGS = get_settings()
client = TestClient(app)


def bearer(role: Role) -> dict:
    return {"Authorization": f"Bearer {create_token('tester', role.value, 'access', SETTINGS)}"}


def test_password_hashing() -> None:
    hashed = hash_password("s3cret-pass")
    assert hashed != "s3cret-pass"
    assert verify_password("s3cret-pass", hashed)
    assert not verify_password("wrong", hashed)
    assert not verify_password("x", None)


def test_token_roundtrip_and_type_check() -> None:
    access = create_token("alice", "ANALYST", "access", SETTINGS)
    assert decode_token(access, "access", SETTINGS)["sub"] == "alice"
    with pytest.raises(TokenError):
        decode_token(access, "refresh", SETTINGS)  # an access token is not a refresh token


def test_expired_token_rejected() -> None:
    past = datetime.now(timezone.utc) - timedelta(hours=1)
    token = pyjwt.encode({"sub": "a", "role": "ADMIN", "type": "access", "iat": past, "exp": past},
                         SETTINGS.jwt_secret, algorithm="HS256")
    with pytest.raises(TokenError, match="expired"):
        decode_token(token, "access", SETTINGS)


def test_tampered_token_rejected() -> None:
    token = pyjwt.encode({"sub": "a", "role": "ADMIN", "type": "access",
                          "exp": datetime.now(timezone.utc) + timedelta(minutes=5)},
                         "a-different-secret-0123456789-0123456789", algorithm="HS256")
    with pytest.raises(TokenError):
        decode_token(token, "access", SETTINGS)


def test_role_hierarchy() -> None:
    assert has_role(Role.ADMIN, Role.VIEWER)
    assert has_role(Role.ANALYST, Role.ANALYST)
    assert not has_role(Role.VIEWER, Role.ANALYST)
    assert not has_role(Role.ANALYST, Role.ADMIN)


def test_endpoints_require_login() -> None:
    assert client.get("/api/v1/rings").status_code == 401
    assert client.get("/api/v1/admin/users").status_code == 401


def test_rbac_enforced_on_endpoints() -> None:
    # Authorisation runs before any database access, so no Neo4j is needed here.
    assert client.get("/api/v1/admin/users", headers=bearer(Role.ANALYST)).status_code == 403
    assert client.post("/api/v1/rings/detect", headers=bearer(Role.VIEWER)).status_code == 403
    assert client.post("/api/v1/risk/propagate/A1", headers=bearer(Role.VIEWER)).status_code == 403


def test_ingestion_requires_api_key() -> None:
    assert client.post("/api/v1/ingest/transaction", json={}).status_code == 401
    assert client.post("/api/v1/score", json={}).status_code == 401


def test_graph_depth_is_validated() -> None:
    response = client.get("/api/v1/graph/neighbourhood/A1?depth=9", headers=bearer(Role.VIEWER))
    assert response.status_code == 422


def test_security_headers_present() -> None:
    headers = client.get("/health").headers
    assert headers["X-Content-Type-Options"] == "nosniff"
    assert headers["X-Frame-Options"] == "DENY"


def test_api_keys_are_random_and_stored_hashed() -> None:
    a, b = generate_key(), generate_key()
    assert a != b and a.startswith("fm_")
    assert hash_key(a) != a and len(hash_key(a)) == 64


def test_sliding_window_rate_limit() -> None:
    window = SlidingWindow(window_s=60)
    assert all(window.allow("k", limit=3) for _ in range(3))
    assert not window.allow("k", limit=3)
    assert window.allow("other", limit=3)
    assert not SlidingWindow().allow("batch", limit=5, cost=6)
