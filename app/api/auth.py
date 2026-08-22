import asyncio
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Annotated, Any

import jwt
from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from google.auth.transport import requests as google_requests
from google.oauth2 import id_token as google_id_token
from pydantic import BaseModel

from app.core.config import Settings


class GoogleIdentity(BaseModel):
    id: str
    email: str
    name: str
    picture: str | None = None


GoogleVerifier = Callable[[str, Settings], Awaitable[GoogleIdentity]]


async def verify_google_identity(token: str, settings: Settings) -> GoogleIdentity:
    client_id = settings.google_client_id
    if not client_id:
        raise RuntimeError("GOOGLE_CLIENT_ID is not configured")
    payload: dict[str, Any] = await asyncio.to_thread(
        google_id_token.verify_oauth2_token,
        token,
        google_requests.Request(),
        client_id,
    )
    if not payload.get("sub") or not payload.get("email"):
        raise ValueError("Google token is missing required identity claims")
    if payload.get("email_verified") is not True:
        raise ValueError("Google email is not verified")
    return GoogleIdentity(
        id=str(payload["sub"]),
        email=str(payload["email"]),
        name=str(payload.get("name") or payload["email"]),
        picture=str(payload["picture"]) if payload.get("picture") else None,
    )


class SessionTokens:
    ISSUER = "parallel-research-consensus"
    AUDIENCE = "research-api"

    def __init__(self, settings: Settings) -> None:
        self._secret = settings.session_secret.get_secret_value()
        self._ttl_seconds = settings.session_ttl_seconds

    @property
    def ttl_seconds(self) -> int:
        return self._ttl_seconds

    def issue(self, identity: GoogleIdentity) -> str:
        if not self._secret:
            raise RuntimeError("SESSION_SECRET is not configured")
        now = datetime.now(UTC)
        return jwt.encode(
            {
                "sub": identity.id,
                "email": identity.email,
                "name": identity.name,
                "iat": now,
                "exp": now + timedelta(seconds=self._ttl_seconds),
                "iss": self.ISSUER,
                "aud": self.AUDIENCE,
            },
            self._secret,
            algorithm="HS256",
        )

    def verify(self, token: str) -> str:
        if not self._secret:
            raise jwt.InvalidTokenError("Session signing secret is not configured")
        payload = jwt.decode(
            token,
            self._secret,
            algorithms=["HS256"],
            audience=self.AUDIENCE,
            issuer=self.ISSUER,
        )
        user_id = payload.get("sub")
        if not isinstance(user_id, str) or not user_id:
            raise jwt.InvalidTokenError("Session token has no subject")
        return user_id


bearer_scheme = HTTPBearer(auto_error=False)


async def get_current_user_id(
    request: Request,
    credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(bearer_scheme)] = None,
    x_user_id: Annotated[str | None, Header(alias="X-User-ID")] = None,
) -> str:
    if credentials:
        try:
            return request.app.state.session_tokens.verify(credentials.credentials)
        except jwt.InvalidTokenError as exc:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid or expired session token",
            ) from exc

    settings: Settings = request.app.state.settings
    if (
        settings.app_env in {"development", "test"}
        and settings.allow_dev_auth
        and x_user_id
        and x_user_id.strip()
    ):
        return x_user_id.strip()
    raise HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Bearer authentication is required",
    )
