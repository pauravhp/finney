"""Select one explicit mailbox transport; failures never fall back to another profile."""

from contextlib import asynccontextmanager

import httpx

from app.config import Settings

from .errors import ConnectionRequired
from .gmail import GMAIL_READ_SCOPE, GmailClient, GmailOAuth


@asynccontextmanager
async def gmail_session(settings: Settings, tokens: dict, connection_data: dict):
    backend = connection_data.get("auth_backend") or settings.finance_gmail_backend
    if backend == "hermes":
        from .hermes_gmail import HermesGmailClient, HermesGmailRuntime

        if tokens.get("type") == "authorized_user":
            credentials = tokens
        else:
            # Compatibility with this app's earlier readonly web OAuth grant.
            # Never discover/import a personal Hermes token or Google CLI profile.
            if not settings.google_client_id or not settings.google_client_secret.get_secret_value():
                raise ConnectionRequired("Reconnect this mailbox using finance gmail-connect")
            credentials = {
                "type": "authorized_user",
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret.get_secret_value(),
                "refresh_token": tokens.get("refresh_token"),
                "token": tokens.get("access_token"),
                "token_uri": "https://oauth2.googleapis.com/token",
                "scopes": [GMAIL_READ_SCOPE],
                "expiry": "1970-01-01T00:00:00Z",
            }
        yield HermesGmailClient(HermesGmailRuntime(settings), credentials)
    elif backend == "api":
        oauth = GmailOAuth(
            settings.google_client_id,
            settings.google_client_secret.get_secret_value(),
            settings.google_redirect_uri,
        )
        async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
            fresh = await oauth.refresh(http, tokens["refresh_token"])
            yield GmailClient(http, fresh["access_token"])
    else:
        raise ConnectionRequired("Unsupported mailbox transport; reconnect the event mailbox")
