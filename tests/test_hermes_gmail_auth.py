"""Consent fixtures plus an offline pinned-Hermes URL smoke; no provider calls."""

from __future__ import annotations

import asyncio
import base64
import copy
import hashlib
import json
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode
from uuid import UUID

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from app.config import Settings
from app.connectors import hermes_gmail_auth as auth
from app.connectors.gmail import GMAIL_READ_SCOPE, GOOGLE_TOKEN_URL
from app.connectors.hermes_gmail_worker import BridgeFailure
from app.connectors.tokens import TokenCipher

ORG, RUN, DIRECTOR = (str(UUID(int=value)) for value in (1, 2, 3))
STATE = "fixture_authorization_state_1234567890"
VERIFIER = "fixture_pkce_verifier_" + "a" * 43
CLIENT = {
    "installed": {
        "client_id": "fixture.apps.googleusercontent.com",
        "client_secret": "fixture-desktop-secret",
        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
        "token_uri": GOOGLE_TOKEN_URL,
        "redirect_uris": ["http://localhost"],
    }
}
CREDENTIALS = {
    "type": "authorized_user",
    "client_id": CLIENT["installed"]["client_id"],
    "client_secret": CLIENT["installed"]["client_secret"],
    "token_uri": GOOGLE_TOKEN_URL,
    "scopes": [GMAIL_READ_SCOPE],
    "refresh_token": "fixture-refresh-token",
    "token": "fixture-access-token",
}


class DatabaseFixture:
    def __init__(self):
        self.rows = {
            "memberships": [
                {"organization_id": ORG, "user_id": DIRECTOR, "role": "director", "active": True}
            ],
            "demo_runs": [
                {
                    "organization_id": ORG,
                    "id": RUN,
                    "status": "active",
                    "is_demo": False,
                    "expires_at": None,
                }
            ],
            "oauth_pending": [],
        }
        self.writes = []
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        pass

    @staticmethod
    def matches(row, filters):
        for key, query in filters.items():
            operator, value = query.split(".", 1)
            actual = row.get(key)
            if operator == "eq":
                if isinstance(actual, bool):
                    actual = str(actual).lower()
                if actual != value:
                    return False
            elif operator == "gt":
                if datetime.fromisoformat(actual) <= datetime.fromisoformat(value):
                    return False
            else:
                raise AssertionError("Unexpected fixture filter")
        return True

    async def select(self, table, *, filters, limit=100, **_kwargs):
        return copy.deepcopy(
            [row for row in self.rows[table] if self.matches(row, filters)][:limit]
        )

    async def insert(self, table, values, **kwargs):
        self.writes.append((table, copy.deepcopy(values), kwargs))
        self.rows[table].append(copy.deepcopy(values))
        return [copy.deepcopy(values)]

    async def update(self, table, values, *, filters):
        self.calls.append(("update", table, copy.deepcopy(filters)))
        results = []
        # No await between matching and mutation: model the conditional PATCH's
        # single-use contract, without claiming an actual PostgreSQL execution.
        for row in self.rows[table]:
            if self.matches(row, filters):
                row.update(values)
                results.append(copy.deepcopy(row))
        return results

    async def rpc(self, name, arguments):
        self.calls.append(("rpc", name, copy.deepcopy(arguments)))
        return {"status": "connected", "connection_id": str(UUID(int=4))}


class RuntimeFixture:
    def __init__(self):
        self.calls = []
        self.credentials = copy.deepcopy(CREDENTIALS)
        self.pending = {
            "state": STATE,
            "code_verifier": VERIFIER,
            "redirect_uri": auth.REDIRECT_URI,
            "created_at": datetime.now(UTC).timestamp(),
        }
        self.authorization_scope = GMAIL_READ_SCOPE
        self.profile_failure = False
        self.profile = {"emailAddress": "fixture@example.test", "historyId": "123"}

    async def request(self, operation, arguments, credentials=None):
        self.calls.append((operation, copy.deepcopy(arguments), copy.deepcopy(credentials)))
        if operation == "auth_begin":
            challenge = (
                base64.urlsafe_b64encode(hashlib.sha256(VERIFIER.encode()).digest())
                .decode()
                .rstrip("=")
            )
            return {
                "pending": copy.deepcopy(self.pending),
                "authorization_url": "https://accounts.google.com/o/oauth2/auth?"
                + urlencode(
                    {
                        "client_id": CLIENT["installed"]["client_id"],
                        "scope": self.authorization_scope,
                        "redirect_uri": auth.REDIRECT_URI,
                        "state": STATE,
                        "response_type": "code",
                        "access_type": "offline",
                        "code_challenge_method": "S256",
                        "code_challenge": challenge,
                    }
                ),
            }
        assert operation == "auth_finish"
        return {"credentials": copy.deepcopy(self.credentials)}


@pytest.fixture
def setup(monkeypatch, tmp_path):
    settings = Settings(
        _env_file=None,
        supabase_url="https://fixture.supabase.co",
        supabase_secret_key="fixture-backend-key",
        finance_token_encryption_key=Fernet.generate_key().decode(),
        organization_id=ORG,
        run_id=RUN,
        finance_gmail_query="label:director-finance",
    )
    client_file = tmp_path / "explicit-desktop-client.json"
    client_file.write_text(json.dumps(CLIENT))
    db, runtime = DatabaseFixture(), RuntimeFixture()
    monkeypatch.setattr(auth, "SupabaseClient", lambda *_args: db)
    monkeypatch.setattr(auth, "HermesGmailRuntime", lambda _settings: runtime)

    class GmailFixture:
        def __init__(self, bridge, credentials):
            assert bridge is runtime
            self.credentials = copy.deepcopy(credentials)

        async def profile(self):
            if runtime.profile_failure:
                raise RuntimeError("fixture-profile-failure")
            # Persist any token refresh that occurred inside Hermes profile.
            self.credentials["token"] = "fixture-refreshed-access-token"
            return runtime.profile

    monkeypatch.setattr(auth, "HermesGmailClient", GmailFixture)
    return settings, client_file, db, runtime


def callback(state=STATE, **extras):
    return (
        auth.REDIRECT_URI
        + "?"
        + urlencode({"state": state, "code": "fixture-one-use-code", **extras})
    )


async def start(setup):
    settings, client_file, *_ = setup
    return await auth.begin(settings, UUID(DIRECTOR), client_file)


async def test_begin_persists_only_encrypted_director_bound_pending_and_safe_url(setup):
    settings, _client_file, db, runtime = setup
    result = await start(setup)
    assert result["status"] == "authorization_required"
    assert result["auth_backend"] == "hermes"
    assert set(result) == {"status", "auth_backend", "authorization_url"}
    table, row, kwargs = db.writes[0]
    assert table == "oauth_pending" and kwargs == {}
    assert row["provider"] == "gmail_hermes" and row["user_id"] == DIRECTOR
    assert row["organization_id"] == ORG and row["run_id"] == RUN
    assert row["state_hash"] == hashlib.sha256(STATE.encode()).hexdigest()
    assert (
        590 < (datetime.fromisoformat(row["expires_at"]) - datetime.now(UTC)).total_seconds() <= 600
    )
    for secret in (VERIFIER, CLIENT["installed"]["client_secret"], STATE):
        assert secret not in json.dumps(row)
    opened = TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
        row["encrypted_verifier"], organization_id=ORG, connection_id=row["state_hash"]
    )
    assert opened == {"client": CLIENT, "pending": runtime.pending}
    with pytest.raises(ValueError, match="scope mismatch"):
        TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
            row["encrypted_verifier"],
            organization_id=str(UUID(int=100)),
            connection_id=row["state_hash"],
        )
    assert runtime.calls == [("auth_begin", {}, CLIENT)]


@pytest.mark.parametrize(
    "change",
    [
        "no_director",
        "finance_role",
        "inactive_director",
        "public_run",
        "closed_run",
        "expired_run",
        "invalid_expiry",
    ],
)
async def test_begin_requires_current_director_and_private_active_unexpired_run(setup, change):
    _settings, _file, db, runtime = setup
    if change == "no_director":
        db.rows["memberships"] = []
    elif change == "finance_role":
        db.rows["memberships"][0]["role"] = "finance"
    elif change == "inactive_director":
        db.rows["memberships"][0]["active"] = False
    elif change == "public_run":
        db.rows["demo_runs"][0]["is_demo"] = True
    elif change == "closed_run":
        db.rows["demo_runs"][0]["status"] = "closed"
    elif change == "expired_run":
        db.rows["demo_runs"][0]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    else:
        db.rows["demo_runs"][0]["expires_at"] = "2026-10-25T00:00:00"
    with pytest.raises(ValueError):
        await start(setup)
    assert not runtime.calls and not db.writes


@pytest.mark.parametrize(
    "setting", ["organization_id", "run_id", "supabase_url", "finance_token_encryption_key"]
)
async def test_begin_requires_explicit_hosted_scope_and_encryption(setup, setting):
    settings, _file, db, runtime = setup
    empty = SecretStr("") if setting == "finance_token_encryption_key" else ""
    setattr(settings, setting, None if setting.endswith("_id") else empty)
    with pytest.raises(ValueError):
        await start(setup)
    assert not runtime.calls and not db.writes


@pytest.mark.parametrize(
    "content",
    [
        "not-json",
        json.dumps({"web": CLIENT["installed"]}),
        json.dumps(CREDENTIALS),
        json.dumps(
            {"installed": {**CLIENT["installed"], "token_uri": "https://example.test/collect"}}
        ),
    ],
)
async def test_begin_requires_explicit_desktop_client_and_canonical_google_endpoints(
    setup, content
):
    _settings, file, db, runtime = setup
    file.write_text(content)
    with pytest.raises(ValueError):
        await start(setup)
    assert not runtime.calls and not db.writes


@pytest.mark.parametrize(
    "query",
    ["", "label:", "in:inbox", "label:director-finance OR in:inbox", "label:finance{in:inbox}"],
)
async def test_begin_refuses_queries_that_can_expand_beyond_one_label(setup, query):
    settings, _file, db, runtime = setup
    settings.finance_gmail_query = query
    with pytest.raises(ValueError, match="finance label"):
        await start(setup)
    assert not runtime.calls and not db.writes


async def test_begin_rejects_broad_hermes_consent_before_pending_is_saved(setup):
    _settings, _file, db, runtime = setup
    runtime.authorization_scope += " https://www.googleapis.com/auth/gmail.modify"
    with pytest.raises(ValueError, match="readonly"):
        await start(setup)
    assert not db.writes


async def test_missing_explicit_client_does_not_search_personal_hermes(setup):
    settings, file, db, runtime = setup
    file.unlink()
    with pytest.raises(ValueError, match="explicit client path"):
        await auth.begin(settings, UUID(DIRECTOR), file)
    assert not db.writes and not runtime.calls


async def test_real_pinned_hermes_auth_begin_is_accepted_offline(setup, monkeypatch):
    """Real URL/PKCE/state generation, with a dummy client and fake DB.

    URL generation invokes no Google API or consent. Runtime installation remains
    optional for clones, so absence is an explicit skip rather than fixture success.
    """
    from app.connectors.hermes_gmail import HermesGmailRuntime
    from app.runtime.hermes import APP_ROOT

    python = APP_ROOT / ".runtime/hermes-venv/bin/python"
    source = APP_ROOT / ".runtime/hermes-source"
    if not python.is_file() or not (source / "hermes_bootstrap.py").is_file():
        pytest.skip("Application's pinned Hermes source and dedicated runtime are not installed")
    settings, _file, db, _runtime = setup
    monkeypatch.setattr(auth, "HermesGmailRuntime", HermesGmailRuntime)
    result = await start(setup)
    assert result["status"] == "authorization_required"
    row = db.rows["oauth_pending"][0]
    opened = TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
        row["encrypted_verifier"], organization_id=ORG, connection_id=row["state_hash"]
    )
    assert len(opened["pending"]["state"]) >= 20
    assert len(opened["pending"]["code_verifier"]) >= 43


async def test_finish_exchanges_after_scope_and_director_checks_then_uses_atomic_rpc(setup):
    settings, _file, db, runtime = setup
    await start(setup)
    result = await auth.finish(settings, callback(scope=GMAIL_READ_SCOPE))
    assert result == {
        "status": "connected",
        "auth_backend": "hermes",
        "query": "label:director-finance",
    }
    consume = next(call for call in db.calls if call[0] == "update")
    assert consume[2]["organization_id"] == "eq." + ORG
    assert consume[2]["run_id"] == "eq." + RUN
    assert consume[2]["provider"] == "eq.gmail_hermes"
    rpc = [call for call in db.calls if call[0] == "rpc"]
    assert len(rpc) == 1 and rpc[0][1] == "connect_hermes_gmail"
    arguments = rpc[0][2]
    assert {key: value for key, value in arguments.items() if key != "p_encrypted_token"} == {
        "p_organization_id": ORG,
        "p_run_id": RUN,
        "p_director_user_id": DIRECTOR,
        "p_mailbox": "fixture@example.test",
        "p_query": "label:director-finance",
    }
    stored = TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
        arguments["p_encrypted_token"], organization_id=ORG, connection_id=f"{RUN}:gmail"
    )
    assert stored == {**CREDENTIALS, "token": "fixture-refreshed-access-token"}
    assert runtime.calls[-1] == (
        "auth_finish",
        {"pending": runtime.pending, "callback_url": callback(scope=GMAIL_READ_SCOPE)},
        CLIENT,
    )
    assert [write[0] for write in db.writes] == ["oauth_pending"]
    for secret in (
        VERIFIER,
        "fixture-access-token",
        "fixture-refresh-token",
        "fixture-one-use-code",
    ):
        assert secret not in json.dumps(result)


@pytest.mark.parametrize(
    "change",
    [
        "wrong_state",
        "expired_pending",
        "changed_scope",
        "revoked_director",
        "public_run",
        "expired_run",
        "tampered_pending_state",
        "expired_encrypted_pending",
        "changed_redirect",
    ],
)
async def test_finish_rejects_invalid_or_revoked_attempt_before_exchange(setup, change):
    settings, _file, db, runtime = setup
    await start(setup)
    url = callback()
    if change == "wrong_state":
        url = callback(state="different_fixture_state_123456789012345")
    elif change == "expired_pending":
        db.rows["oauth_pending"][0]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    elif change == "changed_scope":
        settings.run_id = UUID(int=100)
    elif change == "revoked_director":
        db.rows["memberships"][0]["active"] = False
    elif change == "public_run":
        db.rows["demo_runs"][0]["is_demo"] = True
    elif change == "expired_run":
        db.rows["demo_runs"][0]["expires_at"] = (
            datetime.now(UTC) - timedelta(seconds=1)
        ).isoformat()
    elif change == "changed_redirect":
        db.rows["oauth_pending"][0]["redirect_uri"] = "http://localhost:2"
    else:
        row = db.rows["oauth_pending"][0]
        changed = (
            {"created_at": datetime.now(UTC).timestamp() - 601}
            if change == "expired_encrypted_pending"
            else {"state": "different_fixture_state_123456789012345"}
        )
        row["encrypted_verifier"] = TokenCipher(
            settings.finance_token_encryption_key.get_secret_value()
        ).seal(
            {
                "client": CLIENT,
                "pending": {**runtime.pending, **changed},
            },
            organization_id=ORG,
            connection_id=row["state_hash"],
        )
    with pytest.raises(ValueError):
        await auth.finish(settings, url)
    assert [call[0] for call in runtime.calls] == ["auth_begin"]
    assert not [call for call in db.calls if call[0] == "rpc"]


@pytest.mark.parametrize(
    "url",
    [
        "fixture-one-use-code",
        "https://example.test/?state=test&code=test",
        "http://localhost:2?state=test&code=test",
        "http://localhost:1/callback?state=test&code=test",
        callback() + "#fragment",
        callback() + "&state=duplicate",
        callback() + "&iss=https%3A%2F%2Fexample.test",
        callback() + "&authuser=1&authuser=2",
        callback() + "&unrecognized=1",
        callback(scope=GMAIL_READ_SCOPE + " https://www.googleapis.com/auth/gmail.modify"),
        callback(error="access_denied"),
    ],
)
async def test_finish_requires_full_expected_callback_and_readonly_consent(setup, url):
    settings, _file, db, runtime = setup
    await start(setup)
    with pytest.raises(ValueError):
        await auth.finish(settings, url)
    assert not db.calls
    assert [call[0] for call in runtime.calls] == ["auth_begin"]


async def test_finish_is_single_use_even_after_success(setup):
    settings, _file, db, runtime = setup
    await start(setup)
    await auth.finish(settings, callback())
    with pytest.raises(ValueError, match="already used"):
        await auth.finish(settings, callback())
    assert [call[0] for call in runtime.calls].count("auth_finish") == 1
    assert len([call for call in db.calls if call[0] == "rpc"]) == 1


async def test_finish_accepts_browser_normalized_localhost_slash(setup):
    settings, _file, _db, runtime = setup
    await start(setup)
    normalized = callback().replace("localhost:1?", "localhost:1/?")
    result = await auth.finish(settings, normalized)
    assert result["status"] == "connected"
    assert runtime.calls[-1][1]["callback_url"] == normalized


async def test_simultaneous_finish_attempts_exchange_only_once(setup):
    settings, _file, db, runtime = setup
    await start(setup)
    results = await asyncio.gather(
        auth.finish(settings, callback()), auth.finish(settings, callback()), return_exceptions=True
    )
    assert len([result for result in results if isinstance(result, dict)]) == 1
    assert len([result for result in results if isinstance(result, ValueError)]) == 1
    assert [call[0] for call in runtime.calls].count("auth_finish") == 1
    assert len([call for call in db.calls if call[0] == "rpc"]) == 1


@pytest.mark.parametrize(
    "failure", ["broad_scope", "missing_refresh", "profile_failure", "invalid_profile"]
)
async def test_reconnect_failure_never_overwrites_existing_credentials_or_metadata(setup, failure):
    settings, _file, db, runtime = setup
    # Existing connection state is deliberately outside the consent service's
    # write set until its final atomic RPC. This is a unit boundary assertion.
    db.rows["connector_secrets"] = [{"encrypted_token": "existing-fixture-ciphertext"}]
    db.rows["connections"] = [{"status": "connected", "data": {"history_id": "existing-cursor"}}]
    original = copy.deepcopy((db.rows["connector_secrets"], db.rows["connections"]))
    await start(setup)
    if failure == "broad_scope":
        runtime.credentials["scopes"].append("https://www.googleapis.com/auth/gmail.modify")
    elif failure == "missing_refresh":
        runtime.credentials.pop("refresh_token")
    elif failure == "profile_failure":
        runtime.profile_failure = True
    else:
        runtime.profile = {"emailAddress": "invalid"}
    with pytest.raises((ValueError, RuntimeError)):
        await auth.finish(settings, callback())
    assert not [call for call in db.calls if call[0] == "rpc"]
    assert (db.rows["connector_secrets"], db.rows["connections"]) == original
    with pytest.raises(ValueError, match="already used"):
        await auth.finish(settings, callback())


async def test_explicit_existing_grant_is_copied_encrypted_and_source_unchanged(setup,tmp_path):
    settings,_,db,_=setup
    token=tmp_path/'existing-token.json'
    token.write_text(json.dumps(CREDENTIALS));token.chmod(0o600)
    before=token.read_bytes()
    result=await auth.import_grant(settings,UUID(DIRECTOR),token,expected_mailbox='fixture@example.test')
    assert result['reused_existing_grant'] and result['source_profile_written'] is False
    assert token.read_bytes()==before
    call=next(x for x in db.calls if x[0]=='rpc')
    assert call[1]=='connect_hermes_gmail'
    stored=TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
        call[2]['p_encrypted_token'],organization_id=ORG,connection_id=f'{RUN}:gmail')
    assert stored['token']=='fixture-refreshed-access-token'
    assert 'token' not in json.dumps(result)


@pytest.mark.parametrize('failure',['wrong_mailbox','broad_scope','unsafe_permissions','symlink','not_director','profile_failure'])
async def test_grant_import_failures_never_commit_or_change_personal_source(setup,tmp_path,failure):
    settings,_,db,runtime=setup
    token=tmp_path/'existing-token.json'
    creds=copy.deepcopy(CREDENTIALS)
    if failure=='broad_scope':creds['scopes'].append('https://www.googleapis.com/auth/gmail.send')
    token.write_text(json.dumps(creds));token.chmod(0o644 if failure=='unsafe_permissions' else 0o600)
    before=token.read_bytes();selected=token
    if failure=='symlink':
        selected=tmp_path/'link.json';selected.symlink_to(token)
    if failure=='not_director':db.rows['memberships'][0]['role']='viewer'
    if failure=='profile_failure':runtime.profile_failure=True
    mailbox='wrong@example.test' if failure=='wrong_mailbox' else 'fixture@example.test'
    expected = {"broad_scope": BridgeFailure, "symlink": OSError, "profile_failure": RuntimeError}.get(failure,ValueError)
    with pytest.raises(expected):
        await auth.import_grant(settings,UUID(DIRECTOR),selected,expected_mailbox=mailbox)
    assert not any(x[0]=='rpc' for x in db.calls)
    assert token.read_bytes()==before
