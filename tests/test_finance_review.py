"""Coordinator integration regressions; all providers here are explicit local fixtures."""

from __future__ import annotations

import asyncio
import hashlib
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet

from app.config import Settings
from app.connectors.intake import persist_evidence
from app.connectors.tokens import TokenCipher
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.payments.types import NETWORK, TransferIntent
from app.service import IntegratedTools


@pytest.mark.asyncio
async def test_source_committed_before_case_failure_is_repaired_on_retry():
    class DB:
        def __init__(self):
            self.sources, self.cases = [], []

        async def select(self, table, **kwargs):
            return self.sources if table == "source_items" else self.cases

    class Tools:
        scope = Scope(uuid4(), uuid4())

        def __init__(self, db):
            self.db, self.fail_case = db, True

        async def call(self, name, args):
            if name == "put_artifact":
                return {"artifact_path": "explicit-test-artifact"}
            if name == "record_source":
                row = {"id": str(uuid4()), **args}
                self.db.sources.append(row)
                return row
            if name == "record_case":
                if self.fail_case:
                    self.fail_case = False
                    raise RuntimeError("explicit crash after source commit")
                row = {"id": str(uuid4()), **args}
                self.db.cases.append(row)
                return row
            raise AssertionError(name)

    db = DB()
    tools = Tools(db)
    evidence = {"provider": "gmail", "external_id": "abc", "text": "Test receipt"}
    with pytest.raises(RuntimeError, match="source commit"):
        await persist_evidence(tools, db, evidence)
    assert len(db.sources) == 1 and db.cases == []
    recovered = await persist_evidence(tools, db, evidence)
    assert recovered.get("case_id"), "retry must recover the missing case and review linkage"
    assert len(db.sources) == len(db.cases) == 1


@pytest.mark.asyncio
async def test_agent_proposal_is_augmented_with_trusted_exact_transfer_fields(monkeypatch):
    sender = "0x" + "1" * 40
    scope = Scope(uuid4(), uuid4(), uuid4())
    monkeypatch.setenv("FINANCE_ORGANIZATION_ID", str(scope.organization_id))
    monkeypatch.setenv("FINANCE_RUN_ID", str(scope.run_id))
    monkeypatch.setenv("COINBASE_SENDER_ADDRESS", sender)
    monkeypatch.setenv("COINBASE_MCP_URL", "https://wallet-mcp.coinbase.com")
    monkeypatch.setenv("COINBASE_MCP_TOKEN", "explicit-test-only-oauth-token")

    class DB:
        async def rpc(self, name, args):
            assert name == "finance_kernel_call"
            if args["p_operation"] == "assert_payment_run_authorized":
                return {"authorized": True, "is_demo": False, "organization_id": str(scope.organization_id), "run_id": str(scope.run_id), "sender": sender}
            return {"id": str(uuid4()), **args["p_arguments"]}

    db = DB()
    tools = IntegratedTools(FinanceToolClient(scope, db), db)
    prepared = await tools.call(
        "create_approval_request",
        {
            "action": {
                "type": "payment",
                "amount_minor": 1,
                "currency": "USD",
                "asset": "USDC",
                "network": NETWORK,
                "destination": "0x" + "2" * 40,
                "obligation_id": str(uuid4()),
                "obligation_version": 1,
            },
            "idempotency_key": "review-proposal",
        },
    )
    intent = TransferIntent.from_action(prepared["action"], expected_sender=sender)
    assert intent.amount_base_units == 10_000
    assert prepared["proposed_by"] is None


@pytest.mark.asyncio
@pytest.mark.parametrize("overlapping", [False, True])
async def test_mailbox_reconnect_does_not_keep_a_previous_mailbox_cursor(monkeypatch, overlapping):
    import app.connectors.oauth_api as api

    org, run, user = str(uuid4()), str(uuid4()), str(uuid4())
    state, key = "explicit-review-state", Fernet.generate_key().decode()
    digest = hashlib.sha256(state.encode()).hexdigest()
    settings = Settings(
        _env_file=None,
        supabase_url="https://fixture.invalid",
        supabase_secret_key="sb_secret_explicit_fixture",
        supabase_publishable_key="sb_publishable_explicit_fixture",
        google_client_id="fixture-client",
        google_client_secret="fixture-secret",
        finance_gmail_backend="api",
        google_redirect_uri="http://127.0.0.1/oauth/gmail/callback",
        finance_token_encryption_key=key,
        finance_gmail_query="label:finance",
    )
    pending = {
        "organization_id": org,
        "run_id": run,
        "user_id": user,
        "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
        "redirect_uri": settings.google_redirect_uri,
        "encrypted_verifier": TokenCipher(key).seal(
            {"verifier": "fixture-verifier"}, organization_id=org, connection_id=digest
        ),
    }

    class DB:
        def __init__(self):
            self.data = {
                "mailbox": "previous@example.invalid",
                "history_id": "999",
                "label_id": "Old_label",
            }
            self.first_update_waiting, self.second_update_done = asyncio.Event(), asyncio.Event()
            self.updates, self.consumed = 0, 0

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        async def update(self, table, values, *, filters):
            self.updates += 1
            if overlapping and self.updates == 1:
                self.first_update_waiting.set()
                await self.second_update_done.wait()
            cutoff = datetime.fromisoformat(filters["expires_at"].removeprefix("gt."))
            if datetime.fromisoformat(pending["expires_at"]) <= cutoff:
                return []
            pending["expires_at"] = values["expires_at"]
            self.consumed += 1
            if overlapping:
                self.second_update_done.set()
            return [dict(pending)]

        async def select(self, table, **kwargs):
            if table == "memberships":
                return [{"role": "director"}]
            if table == "demo_runs":
                return [{"is_demo": False, "expires_at": None}]
            if table == "connections":
                return [{"data": self.data}]
            raise AssertionError(table)

        async def insert(self, *args, **kwargs):
            return []

        async def rpc(self, name, args):
            self.data.update(args["p_arguments"]["data"])
            return {}

    db = DB()

    async def exchange(self, http, **kwargs):
        return {"access_token": "explicit-test-access", "refresh_token": "explicit-test-refresh"}

    async def profile(self):
        return {"emailAddress": "new@example.invalid"}

    monkeypatch.setattr(api, "Settings", lambda: settings)
    monkeypatch.setattr(api, "SupabaseClient", lambda *args, **kwargs: db)
    monkeypatch.setattr(api.GmailOAuth, "exchange", exchange)
    monkeypatch.setattr(api.GmailClient, "profile", profile)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=api.create_app()), base_url="http://fixture.invalid"
    ) as http:
        request = lambda: http.get(
            "/oauth/gmail/callback", params={"state": state, "code": "fixture-code"}
        )
        if overlapping:
            first = asyncio.create_task(request())
            await asyncio.wait_for(db.first_update_waiting.wait(), timeout=5)
            second = await request()
            responses = [await first, second]
        else:
            responses = [await request(), await request()]
    assert sorted(response.status_code for response in responses) == [200, 400]
    assert db.consumed == 1
    assert db.data["mailbox"] == "new@example.invalid"
    assert db.data.get("history_id") is None, "new mailbox must begin a new full scan"
    assert db.data.get("label_id") is None


@pytest.mark.asyncio
async def test_failed_review_enqueue_never_advances_gmail_cursor(monkeypatch):
    from app.connectors import gmail_session as transport
    from app.connectors import intake
    from app.connectors.gmail import SyncBatch

    scope = Scope(uuid4(), uuid4())
    key = Fernet.generate_key().decode()
    cipher = TokenCipher(key)
    secret = cipher.seal(
        {"refresh_token": "explicit-fixture-refresh"},
        organization_id=str(scope.organization_id),
        connection_id=f"{scope.run_id}:gmail",
    )
    settings = Settings(
        _env_file=None,
        google_client_id="fixture-client",
        google_client_secret="fixture-secret",
        finance_gmail_backend="api",
        finance_token_encryption_key=key,
        finance_gmail_query="label:finance",
    )
    events = []

    class DB:
        async def select(self, table, **kwargs):
            if table == "connector_secrets":
                return [{"encrypted_token": secret}]
            if table == "connections":
                return [{"data": {"query": "label:finance", "connected_by": str(uuid4())}, "updated_at": "2026-10-24T00:00:00+00:00"}]
            if table == "memberships":
                return [{"role": "director", "active": True}]
            raise AssertionError(table)

        async def update(self, table, values, *, filters):
            assert table == "connections" and filters["updated_at"] == "eq.2026-10-24T00:00:00+00:00"
            events.append("cursor_advanced")
            return [values]

    class Tools:
        def __init__(self):
            self.scope = scope

        async def call(self, name, args):
            assert name == "record_trace"
            events.append("sync_summary")

    class Gmail:
        def __init__(self, *args):
            pass

        async def profile(self):
            return {"emailAddress": "fixture@example.invalid"}

        async def _get(self, *args):
            return {"labels": [{"name": "finance", "id": "Label_finance"}]}

        async def full_sync(self, **kwargs):
            return SyncBatch([{"provider": "gmail", "external_id": "abc"}], "new-cursor")

    async def refresh(self, *args):
        return {"access_token": "fixture-access"}

    async def persist(*args):
        events.append("evidence_persisted")
        return {"source_id": "fixture-source", "case_id": "fixture-case"}

    monkeypatch.setattr(transport, "GmailClient", Gmail)
    monkeypatch.setattr(transport.GmailOAuth, "refresh", refresh)
    monkeypatch.setattr(intake, "persist_evidence", persist)

    async def fail_queue(item):
        events.append("review_enqueue_failed")
        raise RuntimeError("explicit fixture queue failure")

    with pytest.raises(RuntimeError, match="queue failure"):
        await intake.sync_gmail(settings, Tools(), DB(), on_source=fail_queue)
    assert events == ["evidence_persisted", "review_enqueue_failed"]
    events.clear()

    async def queue(item):
        events.append("review_enqueued")

    await intake.sync_gmail(settings, Tools(), DB(), on_source=queue)
    assert events == ["evidence_persisted", "review_enqueued", "cursor_advanced", "sync_summary"]


@pytest.mark.parametrize('retryable,should_block', [(False,True),(True,False)])
async def test_gmail_permanent_failure_stops_auto_intake_without_overwriting_reconnect(monkeypatch,retryable,should_block):
    from contextlib import asynccontextmanager

    from app.connectors import intake
    from app.connectors.errors import ProviderError
    scope=Scope(uuid4(),uuid4());key=Fernet.generate_key().decode()
    secret=TokenCipher(key).seal({'refresh_token':'explicit-fixture'},organization_id=str(scope.organization_id),connection_id=f'{scope.run_id}:gmail')
    updates=[]
    class DB:
        async def select(self,table,**kwargs):
            if table=='connector_secrets':return [{'encrypted_token':secret}]
            if table=='connections':return [{'data':{'query':'label:finance','connected_by':str(uuid4())},'updated_at':'2026-10-24T00:00:00+00:00'}]
            if table=='memberships':return [{'role':'director'}]
            raise AssertionError(table)
        async def update(self,table,values,*,filters):
            updates.append((table,values,filters))
            return []  # Concurrent reconnect changed updated_at; preserve it.
    class Tools:
        def __init__(self):self.scope=scope
    @asynccontextmanager
    async def failing(*args):
        raise ProviderError('gmail',401 if not retryable else 503,retryable=retryable)
        yield  # pragma: no cover
    monkeypatch.setattr(intake,'gmail_session',failing)
    async def on_source(_):raise AssertionError('No source should be imported')
    with pytest.raises(ProviderError):
        await intake.sync_gmail(Settings(_env_file=None,finance_token_encryption_key=key),Tools(),DB(),on_source=on_source)
    assert bool(updates)==should_block
    if updates:
        assert updates[0][1]['status']=='blocked'
        assert updates[0][2]['updated_at']=='eq.2026-10-24T00:00:00+00:00'
        assert 'data' not in updates[0][1]
