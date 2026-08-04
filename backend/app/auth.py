"""Supabase JWT verification.

Every data route depends on :func:`current_user`. The token's signature is
verified against the project's JWT secret rather than merely decoded, so a
client cannot mint its own claims.

This is the actual access control. The backend connects with the service role,
which bypasses RLS, so ownership is enforced by passing the verified user id
into every repository call. The RLS policies exist as a second line of defence
for anything reaching the database by another path.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)

bearer_scheme = HTTPBearer(auto_error=False)


@dataclass(frozen=True)
class AuthenticatedUser:
    id: str
    email: str | None
    role: str


def _unauthorised(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


async def current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(bearer_scheme),
    settings: Settings = Depends(get_settings),
) -> AuthenticatedUser:
    """Verify the bearer token and return the caller."""
    if credentials is None or not credentials.credentials:
        raise _unauthorised("Authentication required.")

    try:
        claims = jwt.decode(
            credentials.credentials,
            settings.supabase_jwt_secret.get_secret_value(),
            algorithms=["HS256"],
            audience="authenticated",
            options={"require": ["exp", "sub"]},
        )
    except jwt.ExpiredSignatureError as exc:
        raise _unauthorised("Session expired. Sign in again.") from exc
    except jwt.InvalidAudienceError as exc:
        raise _unauthorised("Token audience is not 'authenticated'.") from exc
    except jwt.InvalidTokenError as exc:
        # Do not echo the underlying reason: it tells an attacker which part of
        # a forged token to fix next.
        logger.info("Rejected token: %s", exc)
        raise _unauthorised("Invalid authentication token.") from exc

    subject = claims.get("sub")
    if not subject:
        raise _unauthorised("Token has no subject claim.")

    return AuthenticatedUser(
        id=str(subject),
        email=claims.get("email"),
        role=str(claims.get("role", "authenticated")),
    )


def get_repository(request: Request):
    """The shared Repository, created during application startup."""
    repository = getattr(request.app.state, "repository", None)
    if repository is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Database is not available.",
        )
    return repository
