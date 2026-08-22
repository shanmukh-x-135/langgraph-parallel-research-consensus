import jwt
import pytest
from fastapi.testclient import TestClient

from app.api.auth import GoogleIdentity, verify_google_identity
from app.api.jobs import InMemoryJobStore
from app.cache.redis_services import InMemoryCacheRateLimiter
from app.core.config import Settings
from app.main import create_app


async def unused_runner(query, user_id, *, job_id=None):
    raise AssertionError("research runner should not be called")


async def valid_google_verifier(token, settings):
    if token != "valid-google-id-token-value":
        raise ValueError("invalid")
    return GoogleIdentity(
        id="google-user-123",
        email="user@example.com",
        name="Example User",
    )


def auth_app(*, app_env="test", allow_dev_auth=True):
    settings = Settings(
        _env_file=None,
        app_env=app_env,
        allow_dev_auth=allow_dev_auth,
        google_client_id="test-client",
        session_secret="test-session-secret-with-sufficient-length",
        session_ttl_seconds=3600,
    )
    return create_app(
        research_runner=unused_runner,
        job_store=InMemoryJobStore(),
        cache_rate_limiter=InMemoryCacheRateLimiter(),
        settings=settings,
        google_verifier=valid_google_verifier,
    )


def test_google_login_issues_session_for_verified_identity():
    client = TestClient(auth_app())
    response = client.post("/auth/google", json={"id_token": "valid-google-id-token-value"})

    assert response.status_code == 200
    body = response.json()
    assert body["token_type"] == "bearer"
    assert body["expires_in"] == 3600
    assert body["user"]["id"] == "google-user-123"

    protected = client.get(
        "/research/history", headers={"Authorization": f"Bearer {body['access_token']}"}
    )
    assert protected.status_code == 200


def test_invalid_google_token_is_rejected():
    client = TestClient(auth_app())
    response = client.post("/auth/google", json={"id_token": "invalid-google-token-value"})
    assert response.status_code == 401
    assert response.json()["detail"] == "Invalid Google ID token"


def test_invalid_session_token_is_rejected():
    client = TestClient(auth_app())
    response = client.get(
        "/research/history", headers={"Authorization": "Bearer invalid-session-token"}
    )
    assert response.status_code == 401


def test_production_ignores_development_identity_header():
    client = TestClient(auth_app(app_env="production", allow_dev_auth=True))
    response = client.get("/research/history", headers={"X-User-ID": "impersonated-user"})
    assert response.status_code == 401


def test_expired_session_token_is_rejected():
    app = auth_app()
    token = jwt.encode(
        {
            "sub": "user",
            "exp": 1,
            "iss": app.state.session_tokens.ISSUER,
            "aud": app.state.session_tokens.AUDIENCE,
        },
        "test-session-secret-with-sufficient-length",
        algorithm="HS256",
    )
    client = TestClient(app)
    response = client.get("/research/history", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 401


async def test_google_verifier_uses_configured_audience_and_verified_email(monkeypatch):
    captured = {}

    def fake_verify(token, request, audience):
        captured["token"] = token
        captured["audience"] = audience
        return {
            "sub": "google-subject",
            "email": "verified@example.com",
            "email_verified": True,
            "name": "Verified User",
        }

    monkeypatch.setattr("app.api.auth.google_id_token.verify_oauth2_token", fake_verify)
    settings = Settings(_env_file=None, google_client_id="configured-client-id")

    identity = await verify_google_identity("google-token", settings)

    assert identity.id == "google-subject"
    assert captured == {"token": "google-token", "audience": "configured-client-id"}


def test_production_requires_secure_auth_configuration():
    settings = Settings(
        _env_file=None,
        app_env="production",
        google_client_id="client",
        session_secret="short",
    )
    with pytest.raises(ValueError, match="at least 32 characters"):
        create_app(settings=settings)
