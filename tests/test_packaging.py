"""Local packaging/setup tests. Every remote response here is an explicit fixture."""

from __future__ import annotations

import json
import stat
import sys
from uuid import UUID

import pytest

from app.config import Settings
from app.event_setup import event_sql
from app.onboarding import ORDER, STEPS, OnboardingTools, onboard
from app.resources import resource_path
from app.setup_checks import check, doctor

ORG = "fb032dba-9954-45b0-90e2-9a0eb7926b19"
RUN = "989bc434-b516-4d1e-9ce9-f7d97df4924c"
DIRECTOR = "0ec40d3b-1d51-4658-a1a7-06d97f044cdc"
APPROVER = "1ec40d3b-1d51-4658-a1a7-06d97f044cdc"


def config(tmp_path, **overrides):
    values = {
        "supabase_url": "",
        "supabase_secret_key": "",
        "supabase_service_role_key": "",
        "supabase_db_url": "",
        "finance_model_api_key": "",
        "ai_gateway_api_key": "",
        "google_client_id": "",
        "google_client_secret": "",
        "finance_token_encryption_key": "",
        "coinbase_mcp_url": "",
        "organization_id": None,
        "run_id": None,
        "finance_state_dir": tmp_path,
    }
    return Settings(_env_file=None, **(values | overrides))


@pytest.mark.asyncio
async def test_configured_keys_cannot_become_verified_without_live_checks(tmp_path, monkeypatch):
    monkeypatch.setattr("app.setup_checks.runtime_check", lambda settings: check("passed"))
    ready = await doctor(
        config(
            tmp_path,
            supabase_url="https://unit.invalid",
            supabase_secret_key="unit-secret",
            finance_model_api_key="unit-model",
            ai_gateway_api_key="unit-jev",
        )
    )
    assert ready["configuration"]["supabase"] is True
    assert ready["checks"]["supabase_api"]["status"] == "not_run"
    assert ready["ready_for_worker"] is False
    assert ready["ready_for_payments"] is False
    assert "google_sso" not in ready["checks"]
    assert ready["checks"]["dashboard_auth"] == check(
        "not_run", "verify_confirmed_email_password_signin_in_browser"
    )
    assert "unit-secret" not in json.dumps(ready)


@pytest.mark.asyncio
async def test_one_authorization_failure_stops_without_url_key_or_db_retry(tmp_path, monkeypatch):
    from app.storage.supabase import SupabaseError

    calls = []

    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def _request(self, method, path):
            calls.append((method, path))
            raise SupabaseError(401, "invalid_api_key")

    async def provider(settings):
        return check("passed", verification="unit_fixture_only")

    monkeypatch.setattr("app.storage.supabase.SupabaseClient", FixtureClient)
    monkeypatch.setattr("app.setup_checks.runtime_check", lambda settings: check("passed"))
    monkeypatch.setattr("app.setup_checks._model", provider)
    monkeypatch.setattr("app.setup_checks._jev", provider)
    monkeypatch.setattr(
        "psycopg.connect",
        lambda *args, **kwargs: pytest.fail("doctor must not log into PostgreSQL"),
    )
    result = await doctor(
        config(
            tmp_path,
            supabase_url="https://unit.invalid",
            supabase_secret_key="unit-secret",
            supabase_db_url="postgresql://do-not-connect",
            finance_model_api_key="unit-model",
            ai_gateway_api_key="unit-jev",
        ),
        live=True,
    )
    assert calls == [("GET", "/rest/v1/")]
    assert result["checks"]["supabase_api"]["status"] == "blocked"
    assert result["checks"]["supabase_api"]["http_status"] == 401
    assert result["ready_for_worker"] is False


@pytest.mark.asyncio
async def test_agent_requested_verified_status_cannot_override_measured_failure(
    tmp_path, monkeypatch
):
    measured = {
        "configuration": {"supabase": False, "scope": False},
        "checks": {"supabase_api": check("blocked", "fixture_failure")},
        "ready_for_worker": False,
    }
    calls = []

    async def fixture_doctor(settings, *, live):
        calls.append(live)
        return measured

    monkeypatch.setattr("app.setup_checks.doctor", fixture_doctor)
    tools = OnboardingTools(config(tmp_path))
    first = await tools.call(
        "record_setup_progress", {"step": "supabase_api", "status": "verified"}
    )
    await tools.call("record_setup_progress", {"step": "supabase_api", "status": "verified"})
    assert calls == [True]  # one measured probe per session; no provider retry loop
    assert first["checks"]["supabase_api"]["status"] == "blocked"
    assert first["durable_supabase_checkpoint"] is False
    checkpoint = tmp_path / "onboarding.json"
    assert stat.S_IMODE(checkpoint.stat().st_mode) == 0o600
    assert json.loads(checkpoint.read_text())["durable_supabase_checkpoint"] is False
    with pytest.raises(ValueError, match="not permitted"):
        await tools.call("run_shell", {})


@pytest.mark.asyncio
async def test_missing_model_bootstraps_manual_fallback_without_actor_or_network(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(
        "app.setup_checks.runtime_check", lambda settings: check("blocked", "runtime_missing")
    )
    result = await onboard(config(tmp_path))
    assert result["agent_status"] == "bootstrap_model_access_required"
    assert result["status"] == "setup_required"
    assert result["readiness"]["live_requested"] is False
    assert result["checkpoint"]["durable_supabase_checkpoint"] is False
    assert result["next_steps"][0]["step"] == "model"
    assert "dashboard_auth" in {step["step"] for step in result["next_steps"]}


def test_shared_event_plan_requires_confirmed_email_password_users_and_is_restart_safe(tmp_path):
    path = tmp_path / "plan.json"
    kwargs = {
        "name": "Organizer's event",
        "director_user_id": DIRECTOR,
        "approver_user_id": APPROVER,
        "currency": "USD",
        "plan_path": path,
    }
    sql = event_sql(**kwargs)
    assert event_sql(**kwargs) == sql
    assert "join auth.identities" in sql and "i.provider='email'" in sql
    assert "u.email_confirmed_at is not null" in sql
    assert "u.is_anonymous is false" in sql
    assert "nullif(u.encrypted_password,'') is not null" in sql
    assert "insert into auth.users" not in sql
    assert "Organizer''s event" in sql
    assert "on conflict(organization_id,user_id) do nothing" in sql
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert UUID(json.loads(path.read_text())["organization_id"])
    with pytest.raises(ValueError, match="distinct"):
        event_sql(**(kwargs | {"approver_user_id": DIRECTOR}))
    with pytest.raises(ValueError, match="differs"):
        event_sql(**(kwargs | {"name": "Changed ownership"}))


def test_onboarding_separates_email_password_accounts_from_mailbox_oauth():
    assert "dashboard_auth" in ORDER and "google_sso" not in STEPS
    assert "confirm their emails" in STEPS["dashboard_auth"]
    assert "Keep email confirmation enabled" in STEPS["dashboard_auth"]
    assert "Authentication > Users" in STEPS["scope"]
    assert "Desktop OAuth client" in STEPS["gmail_oauth"]
    assert "dashboard Web client" not in STEPS["gmail_oauth"]
    assert "does not grant mailbox access" in STEPS["gmail_connection"]


def test_director_only_event_plan_has_stable_ids_and_no_placeholder_approver(tmp_path):
    path = tmp_path / "plan.json"
    kwargs = {
        "name": "Director's private event",
        "director_user_id": DIRECTOR,
        "currency": "USD",
        "plan_path": path,
    }
    sql = event_sql(**kwargs)
    plan = json.loads(path.read_text())
    assert event_sql(**kwargs) == sql
    assert plan["approver_user_id"] is None
    assert "approver uuid := null;" in sql
    assert "false as approver_configured" in sql
    assert "No separate approver configured; director selects the event payment approval policy." in sql
    # Changing membership authority must not silently reuse the bootstrap plan.
    with pytest.raises(ValueError, match="differs"):
        event_sql(**kwargs, approver_user_id=APPROVER)


def test_event_sql_cli_accepts_director_without_approver(tmp_path, monkeypatch, capsys):
    from app.cli import main

    monkeypatch.setattr("app.cli.Settings", lambda: config(tmp_path))
    monkeypatch.setattr(
        sys, "argv", ["finance", "event-sql", "--name", "Director event",
                      "--director-user-id", DIRECTOR],
    )
    main()
    assert "false as approver_configured" in capsys.readouterr().out
    assert json.loads((tmp_path / "event-plan.json").read_text())["approver_user_id"] is None


def test_oauth_server_factory_defaults_disable_access_logs(tmp_path, monkeypatch):
    from app.cli import main

    called = []
    monkeypatch.setattr("app.cli.Settings", lambda: config(tmp_path))
    monkeypatch.setattr(sys, "argv", ["finance", "oauth-server"])
    monkeypatch.setattr("uvicorn.run", lambda *args, **kwargs: called.append((args, kwargs)))
    main()
    assert called == [
        (
            ("app.connectors.oauth_api:create_app",),
            {
                "factory": True,
                "host": "127.0.0.1",
                "port": 8767,
                "access_log": False,
                "log_level": "warning",
            },
        )
    ]


def test_migration_tls_and_first_auth_failure_do_not_leak_or_retry(tmp_path, monkeypatch, capsys):
    from app.cli import main

    calls = []

    def reject(*args, **kwargs):
        calls.append(kwargs)
        raise RuntimeError("unit-password-that-must-not-appear")

    monkeypatch.setattr(
        "app.cli.Settings", lambda: config(tmp_path, supabase_db_url="postgresql://unit.invalid/db")
    )
    monkeypatch.setattr("psycopg.connect", reject)
    monkeypatch.setattr(sys, "argv", ["finance", "migrate"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 1
    assert len(calls) == 1 and calls[0]["sslmode"] == "require"
    assert "unit-password-that-must-not-appear" not in capsys.readouterr().err


def test_source_assets_are_resolved_without_parent_private_research():
    assert resource_path("skills/onboarding/SKILL.md").is_file()
    assert resource_path("supabase/migrations").is_dir()
    with pytest.raises(ValueError):
        resource_path("../private-research.md")


@pytest.mark.asyncio
@pytest.mark.parametrize("outcome", ["terminal", "retryable", "auth_failure"])
async def test_worker_dispatches_with_actual_bound_scope(tmp_path, monkeypatch, capsys, outcome):
    from app.cli import run_worker

    calls = []
    job = {
        "id": RUN,
        "organization_id": ORG,
        "run_id": RUN,
        "requested_by": DIRECTOR,
        "lease_token": APPROVER,
        "command_type": "generate_report",
    }

    class FixtureClient:
        def __init__(self, *args, **kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    class FixtureQueue:
        def __init__(self, client, worker_id):
            pass

        async def lease(self, **kwargs):
            return job

        async def ack(self, *args):
            calls.append(("ack", args))

        async def fail(self, *args, **kwargs):
            calls.append(("fail", kwargs))

    async def dispatch(settings, leased, tools, db):
        assert tools.scope.organization_id == UUID(ORG)
        assert tools.scope.run_id == UUID(RUN)
        assert leased is job
        calls.append(("dispatch", leased["command_type"]))
        if outcome == "auth_failure":
            from app.storage.supabase import SupabaseError

            raise SupabaseError(401, "fixture_auth_failure")
        return {
            "status": "blocked",
            "reason": "unit_fixture_only",
            "retryable": outcome == "retryable",
        }

    monkeypatch.setattr("app.storage.supabase.SupabaseClient", FixtureClient)
    monkeypatch.setattr("app.finance.jobs.JobQueue", FixtureQueue)
    monkeypatch.setattr("app.service.dispatch_job", dispatch)

    def unexpected_scheduler(*args, **kwargs):
        pytest.fail("--once must not create or poll automatic discovery")

    monkeypatch.setattr("app.scheduler.GmailIntakeScheduler", unexpected_scheduler)
    invocation = run_worker(
        config(tmp_path, supabase_url="https://unit.invalid", supabase_secret_key="unit-secret"),
        once=True,
    )
    if outcome == "auth_failure":
        with pytest.raises(RuntimeError, match="authorization_failed_stop_without_retry"):
            await invocation
        assert calls == [("dispatch", "generate_report")]
        return
    await invocation
    assert calls[0] == ("dispatch", "generate_report")
    assert calls[1][0] == ("fail" if outcome == "retryable" else "ack")
    if outcome == "retryable":
        assert calls[1][1]["retryable"] is True
    assert json.loads(capsys.readouterr().out)["status"] == "blocked"


def test_manual_sql_renderer_keeps_migration_hash_receipts_and_avoids_network():
    import hashlib

    from app.setup_sql import migration_sql

    rendered = migration_sql()
    assert "pg_advisory_xact_lock" in rendered
    assert "finance_schema_migrations" in rendered
    for migration in resource_path("supabase/migrations").glob("*.sql"):
        assert migration.name in rendered
        assert hashlib.sha256(migration.read_bytes()).hexdigest() in rendered
    assert rendered.strip().endswith("commit;")


def test_copied_environment_example_can_bootstrap_with_empty_optional_fields(tmp_path, monkeypatch):
    from pathlib import Path

    example = Path(__file__).resolve().parents[1] / ".env.example"
    copied = tmp_path / ".env"
    copied.write_text(example.read_text())
    for line in example.read_text().splitlines():
        if line and not line.startswith("#") and "=" in line:
            monkeypatch.delenv(line.split("=", 1)[0], raising=False)
    loaded = Settings(_env_file=copied)
    assert loaded.organization_id is None and loaded.run_id is None
    assert loaded.configured()["model"] is False


def test_invalid_configuration_uses_safe_cli_error_boundary(tmp_path, monkeypatch, capsys):
    from app.cli import main

    def invalid():
        raise ValueError("unit-private-validation-input")

    monkeypatch.setattr("app.cli.Settings", invalid)
    monkeypatch.setattr(sys, "argv", ["finance", "doctor"])
    with pytest.raises(SystemExit) as result:
        main()
    assert result.value.code == 1
    captured = capsys.readouterr()
    assert "unit-private-validation-input" not in captured.err
    assert json.loads(captured.err)["error_type"] == "ValueError"
