from urllib.parse import urlencode

import requests

from app.core.config import Settings

GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"


def google_authorization_url(settings: Settings, state: str) -> str:
    if not settings.google_client_id or not settings.google_redirect_uri:
        raise ValueError("Google OAuth client and redirect URI must be configured")
    parameters = {
        "client_id": settings.google_client_id,
        "redirect_uri": settings.google_redirect_uri,
        "response_type": "code",
        "scope": "openid email profile",
        "state": state,
        "prompt": "select_account",
    }
    return f"{GOOGLE_AUTH_URL}?{urlencode(parameters)}"


def exchange_google_code(settings: Settings, code: str) -> str:
    response = requests.post(
        GOOGLE_TOKEN_URL,
        data={
            "code": code,
            "client_id": settings.google_client_id,
            "client_secret": settings.google_client_secret.get_secret_value(),
            "redirect_uri": settings.google_redirect_uri,
            "grant_type": "authorization_code",
        },
        timeout=15,
    )
    response.raise_for_status()
    token = response.json().get("id_token")
    if not token:
        raise ValueError("Google token response did not contain an ID token")
    return str(token)


class ResearchApiClient:
    def __init__(self, base_url: str, access_token: str | None = None) -> None:
        self._base_url = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {access_token}"} if access_token else {}

    def _request(self, method: str, path: str, **kwargs):
        response = requests.request(
            method,
            f"{self._base_url}{path}",
            headers=self._headers,
            timeout=30,
            **kwargs,
        )
        response.raise_for_status()
        return response.json()

    def login_google(self, id_token: str) -> dict:
        return self._request("POST", "/auth/google", json={"id_token": id_token})

    def start_research(self, query: str) -> dict:
        return self._request("POST", "/research", json={"query": query})

    def status(self, job_id: str) -> dict:
        return self._request("GET", f"/research/{job_id}/status")

    def report(self, job_id: str) -> dict:
        return self._request("GET", f"/research/{job_id}")

    def history(self) -> list[dict]:
        return self._request("GET", "/research/history")
