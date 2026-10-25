"""Read-only setup probes. Configuration presence is never a successful provider check.

No direct PostgreSQL authentication, credential guessing, alternate URL attempt or
provider retry occurs here. Run migrations separately with the exact owner URL.
"""

from __future__ import annotations

import asyncio
import subprocess
import tempfile
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

import httpx

from app.config import Settings


def check(status: str, reason: str | None = None, **evidence: object) -> dict:
    return {"status": status, **({"reason": reason} if reason else {}), **evidence}


def runtime_check(settings: Settings) -> dict:
    from app.models import ModelError
    from app.runtime.hermes import APP_ROOT, PIN, verify_source

    source = (
        Path(settings.finance_hermes_source)
        if settings.finance_hermes_source
        else APP_ROOT / ".runtime/hermes-source"
    )
    python = settings.finance_hermes_python or str(APP_ROOT / ".runtime/hermes-venv/bin/python")
    try:
        verify_source(source.resolve())
        with tempfile.TemporaryDirectory(prefix="finance-runtime-check-") as directory:
            result = subprocess.run(
                [
                    python,
                    "-I",
                    "-c",
                    "import anthropic, openai, httpx, pydantic, yaml, googleapiclient, google_auth_oauthlib; print('runtime_dependencies_ok')",
                ],
                cwd=directory,
                env={"PATH": "/usr/bin:/bin", "HOME": directory, "PYTHONDONTWRITEBYTECODE": "1"},
                capture_output=True,
                timeout=15,
                check=False,
            )
        if result.returncode or result.stdout.strip() != b"runtime_dependencies_ok":
            return check("blocked", "runtime_dependencies_missing")
        return check(
            "passed", revision=PIN["revision"], verification="source_hash_and_dependency_imports"
        )
    except ModelError as error:
        return check("blocked", error.code)
    except (OSError, subprocess.SubprocessError):
        return check("blocked", "runtime_interpreter_unavailable")


def callback_check(settings: Settings) -> dict:
    url = urlsplit(settings.google_redirect_uri)
    local = url.hostname in {"127.0.0.1", "localhost", "::1"}
    if not url.hostname or url.username or url.password or url.query or url.fragment:
        return check("blocked", "invalid_google_redirect_uri")
    if url.scheme != "https" and not (url.scheme == "http" and local):
        return check("blocked", "google_callback_requires_https_or_loopback")
    return check("not_run", "google_client_registration_and_consent_unverified")


async def _supabase(settings: Settings, checks: dict) -> None:
    from app.storage.supabase import SupabaseClient, SupabaseError

    stage = "supabase_api"
    try:
        async with SupabaseClient(settings.supabase_url, settings.backend_key, timeout=15) as db:
            response = await db._request("GET", "/rest/v1/")
            if response.status_code != 200:
                checks["supabase_api"] = check(
                    "blocked", "unexpected_api_status", http_status=response.status_code
                )
                return
            checks["supabase_api"] = check(
                "passed", verification="authenticated_rest_response", http_status=200
            )
            stage = "database_schema"
            paths = response.json().get("paths", {})
            required = {
                "/organizations",
                "/memberships",
                "/demo_runs",
                "/rpc/get_finance_snapshot",
                "/rpc/finance_kernel_call",
                "/rpc/lease_finance_job",
                "/rpc/get_finance_budget",
                "/rpc/propose_finance_budget",
                "/rpc/connect_hermes_gmail",
                "/rpc/assert_finance_demo_owner",
            }
            checks["database_schema"] = (
                check("passed", verification="required_rest_tables_and_rpcs")
                if required <= set(paths)
                else check("blocked", "finance_migrations_missing_or_api_schema_stale")
            )
            if (
                settings.organization_id
                and settings.run_id
                and checks["database_schema"]["status"] == "passed"
            ):
                stage = "scope"
                snapshot = await db.rpc(
                    "get_finance_snapshot",
                    {
                        "p_organization_id": str(settings.organization_id),
                        "p_run_id": str(settings.run_id),
                    },
                )
                matches = snapshot.get("organization", {}).get("id") == str(
                    settings.organization_id
                ) and snapshot.get("run", {}).get("id") == str(settings.run_id)
                checks["scope"] = (
                    check("passed", verification="scoped_snapshot_read")
                    if matches and snapshot["run"]["status"] == "active"
                    else check("blocked", "scope_missing_mismatched_or_inactive")
                )
                wallet = next((connection for connection in snapshot.get("connections", []) if connection.get("provider") == "coinbase_wallet"), None)
                if wallet:
                    checks["coinbase"] = check("not_run" if wallet.get("status") == "connected" else "blocked",
                                               "stored_grant_present_wallet_identity_and_settlement_unverified" if wallet.get("status") == "connected" else "coinbase_reconnect_required",
                                               verification="scoped_connection_metadata_only")
            stage = "private_storage"
            bucket = await db._request("GET", "/storage/v1/bucket/finance-artifacts")
            checks["private_storage"] = (
                check("passed", verification="private_bucket_configuration_only")
                if bucket.status_code == 200 and bucket.json().get("public") is False
                else check("blocked", "private_artifact_bucket_missing_or_public")
            )
    except SupabaseError as error:
        # One failed authorization ends this invocation; no alternate key/URL or retry.
        checks[stage] = check("blocked", "supabase_request_failed", http_status=error.status)
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        checks[stage] = check("blocked", "supabase_probe_failed")


async def _model(settings: Settings) -> dict:
    from app.models import GenerativeModel, ModelConfig, ModelError

    try:
        config = replace(ModelConfig.from_settings(settings), max_tokens=64)
        result = await GenerativeModel(config).complete(
            'This is a connection check. Return exactly one JSON object: {"status":"ok"}.',
            "No financial actions. Confirm the connection only.",
        )
        if result["output"] != {"status": "ok"}:
            return check("blocked", "model_probe_response_invalid")
        return check("passed", verification="live_model_response_only", **result["evidence"])
    except ModelError as error:
        return check(
            "blocked", error.code, **({"http_status": error.status} if error.status else {})
        )


async def _jev(settings: Settings) -> dict:
    from app.models import JevClient, ModelError

    try:
        result = await JevClient(settings.ai_gateway_api_key.get_secret_value()).evaluate_trace(
            {
                "setup_probe": True,
                "actions": [],
                "note": "Connectivity check only. No financial work or completion claim.",
            }
        )
        return check(
            "passed",
            verification="live_jev_schema_response_only",
            generation_id=result.get("generation_id"),
            provider_request_id=result.get("provider_request_id"),
            usage=result.get("usage"),
            latency_seconds=result.get("latency_seconds"),
        )
    except ModelError as error:
        return check(
            "blocked", error.code, **({"http_status": error.status} if error.status else {})
        )


async def _gmail(settings: Settings) -> dict:
    from app.connectors.errors import ConnectionRequired, ProviderError
    from app.connectors.gmail_session import gmail_session
    from app.connectors.tokens import TokenCipher
    from app.storage.supabase import SupabaseClient, SupabaseError

    try:
        org, run = str(settings.organization_id), str(settings.run_id)
        async with SupabaseClient(settings.supabase_url, settings.backend_key, timeout=15) as db:
            rows = await db.select(
                "connector_secrets",
                filters={
                    "organization_id": "eq." + org,
                    "run_id": "eq." + run,
                    "provider": "eq.gmail",
                },
                limit=1,
            )
            if not rows:
                return check("blocked", "director_mailbox_consent_required")
            connections = await db.select(
                "connections",
                filters={"organization_id": "eq." + org, "run_id": "eq." + run, "provider": "eq.gmail"},
                limit=1,
            )
            data = connections[0].get("data", {}) if connections else {}
            if not data.get("connected_by"):
                return check("blocked", "director_mailbox_consent_required")
            directors = await db.select(
                "memberships",
                filters={"organization_id": "eq." + org, "user_id": "eq." + str(data["connected_by"]),
                         "role": "eq.director", "active": "eq.true"},
                limit=1,
            )
            if not directors:
                return check("blocked", "mailbox_director_authority_changed")
            tokens = TokenCipher(settings.finance_token_encryption_key.get_secret_value()).open(
                rows[0]["encrypted_token"], organization_id=org, connection_id=f"{run}:gmail"
            )
            async with gmail_session(settings, tokens, data) as gmail:
                profile = await gmail.profile()
            if not profile.get("emailAddress"):
                return check("blocked", "gmail_profile_invalid")
            return check(
                "passed", verification="live_credentials_and_profile_only_no_messages_imported",
                backend=data.get("auth_backend") or settings.finance_gmail_backend,
            )
    except (ConnectionRequired, ProviderError, SupabaseError, httpx.HTTPError, ValueError, KeyError):
        return check("blocked", "gmail_consent_or_profile_check_failed")


async def doctor(settings: Settings, *, live: bool = False) -> dict:
    configuration = settings.configured()
    checks = {
        name: check("not_run", "live_probe_required")
        if present
        else check("blocked", "configuration_missing")
        for name, present in configuration.items()
    }
    # A DB connection string is for the explicit migration runner, not evidence
    # that migrations ran. Never authenticate to PostgreSQL from doctor/init.
    checks["database_migrations"] = check("not_run", "use_finance_migrate_and_verify_schema")
    checks["database_schema"] = check("not_run", "live_rest_schema_probe_required")
    checks["supabase_api"] = (
        check("not_run", "live_probe_required")
        if configuration["supabase"]
        else check("blocked", "configuration_missing")
    )
    checks["private_storage"] = check("not_run", "live_private_bucket_probe_required")
    checks["dashboard_auth"] = check("not_run", "verify_confirmed_email_password_signin_in_browser")
    checks["gmail_oauth"] = (
        check("not_run", "run_finance_gmail_connect_for_isolated_hermes_consent")
        if settings.finance_gmail_backend == "hermes"
        else callback_check(settings) if configuration["gmail_oauth"]
        else check("blocked", "configuration_missing")
    )
    checks["gmail_connection"] = check(
        "not_run", "director_consent_and_live_profile_probe_required"
    )
    checks["coinbase"] = (
        check("not_run", "optional_real_testnet_receipt_verification_required")
        if configuration["coinbase"]
        else check("optional", "not_configured_payments_disabled")
    )
    checks["hermes"] = await asyncio.to_thread(runtime_check, settings)
    if configuration["token_encryption"]:
        from app.connectors.tokens import TokenCipher

        try:
            TokenCipher(settings.finance_token_encryption_key.get_secret_value())
            checks["token_encryption"] = check("passed", verification="local_key_format_only")
        except (ValueError, TypeError):
            checks["token_encryption"] = check("blocked", "invalid_encryption_key")
    if live:
        if configuration["supabase"]:
            await _supabase(settings, checks)
        # Probe each provider once, with no retries or fallback credentials.
        if configuration["model"]:
            checks["model"] = await _model(settings)
        if configuration["jev"]:
            checks["jev"] = await _jev(settings)
        if (
            all(
                checks.get(name, {}).get("status") == "passed"
                for name in ("supabase_api", "database_schema", "scope", "token_encryption")
            )
            and (settings.finance_gmail_backend == "hermes" or configuration["gmail_oauth"])
        ):
            checks["gmail_connection"] = await _gmail(settings)
            if checks["gmail_connection"]["status"] == "passed":
                checks["gmail_oauth"] = check("passed", verification="actual_connected_mailbox_profile")
    else:
        checks["supabase_api"] = (
            check("not_run", "live_probe_required")
            if configuration["supabase"]
            else check("blocked", "configuration_missing")
        )
    checks.setdefault("supabase_api", check("blocked", "configuration_missing"))
    required = ("supabase_api", "database_schema", "private_storage", "hermes", "model", "jev")
    ready = all(checks.get(name, {}).get("status") == "passed" for name in required)
    return {
        "configuration": configuration,
        "checks": checks,
        "live_requested": live,
        "ready_for_worker": ready,
        "ready_for_intake": ready
        and checks["scope"]["status"] == "passed"
        and checks["gmail_connection"]["status"] == "passed",
        "ready_for_payments": False,
        "payment_gate": "requires_current_event_human_approval_policy_and_provider_verified_testnet_receipt",
        "verification_limits": [
            "Confirmed email/password dashboard sign-in must be checked in the browser",
            "Private Storage configuration is not a write/read proof",
            "No financial accuracy or improvement is inferred from connection probes",
        ],
    }
