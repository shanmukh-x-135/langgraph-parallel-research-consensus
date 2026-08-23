from urllib.parse import parse_qs, urlsplit

import pytest

from app.core.config import Settings
from streamlit_app.client import ResearchApiClient, exchange_google_code, google_authorization_url


def ui_settings():
    return Settings(
        _env_file=None,
        google_client_id="google-client",
        google_client_secret="google-secret",
        google_redirect_uri="http://localhost:8501",
    )


def test_google_authorization_url_contains_state_and_required_openid_scope():
    url = google_authorization_url(ui_settings(), "csrf-state")
    query = parse_qs(urlsplit(url).query)
    assert query["client_id"] == ["google-client"]
    assert query["state"] == ["csrf-state"]
    assert "openid" in query["scope"][0]
    assert query["redirect_uri"] == ["http://localhost:8501"]


def test_google_code_exchange_returns_id_token(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"id_token": "google-id-token"}

    monkeypatch.setattr("streamlit_app.client.requests.post", lambda *args, **kwargs: Response())
    assert exchange_google_code(ui_settings(), "authorization-code") == "google-id-token"


def test_api_client_sends_bearer_token_and_uses_stored_report_endpoint(monkeypatch):
    captured = {}

    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {"job_id": "job-1"}

    def fake_request(method, url, **kwargs):
        captured.update(method=method, url=url, **kwargs)
        return Response()

    monkeypatch.setattr("streamlit_app.client.requests.request", fake_request)
    client = ResearchApiClient("http://api:8000/", "session-token")
    client.report("job-1")

    assert captured["method"] == "GET"
    assert captured["url"] == "http://api:8000/research/job-1"
    assert captured["headers"] == {"Authorization": "Bearer session-token"}


def test_google_code_exchange_rejects_missing_id_token(monkeypatch):
    class Response:
        def raise_for_status(self):
            return None

        def json(self):
            return {}

    monkeypatch.setattr("streamlit_app.client.requests.post", lambda *args, **kwargs: Response())
    with pytest.raises(ValueError, match="ID token"):
        exchange_google_code(ui_settings(), "authorization-code")
