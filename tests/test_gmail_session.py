"""Explicit transport fixtures: routing evidence, never a live mailbox claim."""

import pytest

from app.config import Settings
from app.connectors import hermes_gmail
from app.connectors.errors import ConnectionRequired, ProviderError
from app.connectors.gmail_session import gmail_session


@pytest.mark.asyncio
async def test_default_transport_uses_hermes_without_legacy_oauth_keys(monkeypatch):
    settings = Settings(_env_file=None, google_client_id="", google_client_secret="")
    credentials = {"type": "authorized_user", "fixture": True}
    seen = []
    runtime = object()

    class FixtureClient:
        def __init__(self, actual_runtime, actual_credentials):
            seen.append((actual_runtime, actual_credentials))

        async def profile(self):
            return {"emailAddress": "fixture@example.invalid"}

    monkeypatch.setattr(hermes_gmail, "HermesGmailRuntime", lambda actual: runtime)
    monkeypatch.setattr(hermes_gmail, "HermesGmailClient", FixtureClient)
    async with gmail_session(settings, credentials, {}) as client:
        assert (await client.profile())["emailAddress"] == "fixture@example.invalid"
    assert seen == [(runtime, credentials)]


@pytest.mark.asyncio
async def test_native_failure_never_falls_back_to_http_or_personal_profile(monkeypatch):
    calls = []

    def unavailable(*args):
        calls.append("native")
        raise ProviderError("explicit_fixture_failure")

    monkeypatch.setattr(hermes_gmail, "HermesGmailRuntime", unavailable)
    with pytest.raises(ProviderError):
        async with gmail_session(Settings(_env_file=None), {"type": "authorized_user"}, {}):
            pytest.fail("failed connector cannot yield a client")
    assert calls == ["native"]


@pytest.mark.asyncio
async def test_unknown_backend_and_legacy_grant_without_keys_require_reconnection():
    settings = Settings(_env_file=None, google_client_id="", google_client_secret="")
    for tokens, data in [({}, {"auth_backend": "unknown"}), ({"refresh_token": "fixture"}, {})]:
        with pytest.raises(ConnectionRequired):
            async with gmail_session(settings, tokens, data):
                pytest.fail("incomplete connector cannot yield a client")
