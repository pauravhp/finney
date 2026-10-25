"""Resumable assistance. Deterministic probes own readiness, never agent assertions."""

from __future__ import annotations

import asyncio
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path

from app.config import Settings
from app.resources import resource_path

STEPS = {
    "model": "Bootstrap model access first. Set FINANCE_MODEL, FINANCE_MODEL_BASE_URL, FINANCE_MODEL_API_MODE and FINANCE_MODEL_API_KEY privately, using one supported provider configuration from README. finance init cannot run inference without this. finance doctor --live makes one small real request; entered keys alone are not verification.",
    "hermes": "Run uv run python -m app.runtime.bootstrap --install. It obtains the exact public revision and verifies the full source digest, then installs frozen dependencies in a separate runtime environment. Never point at a personal Hermes profile or dotenv. Rerun the same command to resume.",
    "supabase_api": "Use the event-owned dedicated Supabase project. Copy its HTTPS project URL, publishable key and backend secret key to the protected environment. Never paste secret values into chat. No URL/key guessing or alternate authentication retries.",
    "database_schema": "Apply the bundled versioned finance migrations. Use the SQL editor or finance migrate with the exact owner-supplied session-pooler URI. Stop immediately on authentication failure; check the owner's dashboard before any further attempt. finance doctor --live checks REST schema without PostgreSQL login.",
    "private_storage": "The migration creates private finance-artifacts Storage and run-scoped policies. Verify a real artifact write/read in the actual event; a private-bucket configuration check alone does not prove it.",
    "dashboard_auth": "Use Supabase Auth email/password sign-in. Have the director and a distinct real approver create accounts in the dashboard and confirm their emails, or have the owner create confirmed accounts with passwords in Supabase Authentication > Users for those actual people. Keep email confirmation enabled by default. Verify each person's dashboard sign-in. Dashboard accounts require no Google client or Gmail grant.",
    "scope": "Use finance event-sql with the confirmed director user ID from Supabase Authentication > Users to prepare a private event; --approver-user-id is optional. The generated SQL validates actual confirmed nonanonymous email/password identities and preserves IDs on resume. Copy organization/run IDs to FINANCE_ORGANIZATION_ID and FINANCE_RUN_ID. The director chooses one-director or two-person payment approval in the Approvals panel; agents cannot change this setting.",
    "token_encryption": "Generate one Fernet key locally using the README command and store it privately as FINANCE_TOKEN_ENCRYPTION_KEY. Retain it with the encrypted Supabase token backups; replacing it without reauthorization makes old mailbox grants unreadable.",
    "gmail_oauth": "Default mailbox transport is isolated Hermes. Enable Gmail API and create a Desktop OAuth client for the director's mailbox, independently of dashboard email/password accounts. Download its JSON privately. After shared-event setup, run finance gmail-connect --client-file PATH --director-user-id UUID on the worker host, approve the generated Google URL, then finance gmail-connect --complete and paste the full localhost redirect into the hidden terminal prompt. Credentials are encrypted in Supabase; personal Hermes is never used. An explicitly selected existing owner-private readonly grant can instead be reused with --import-token-file and --expected-mailbox, without modifying its source profile. See README for prerequisites and the optional legacy API route.",
    "gmail_connection": "Complete finance gmail-connect for a current director of an active private shared event. Add only intended finance messages to the configured director-finance Gmail label. Run finance doctor --live to verify credentials/profile through isolated Hermes without importing messages; queue one label intake in the dashboard or start the background worker. Missing consent remains blocked. Dashboard email/password sign-in does not grant mailbox access.",
    "jev": "Configure AI_GATEWAY_API_KEY separately from the actor model key. The integration uses the real Typesafe decision endpoint through Vercel AI Gateway. finance doctor --live verifies one real schema response, not finance accuracy or improvement.",
    "web": "In web/, set NEXT_PUBLIC_SUPABASE_URL and NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY, then npm ci and npm run dev. Open 127.0.0.1:3000 for local iteration. Follow README's explicit owner-controlled Vercel configuration for hosting; never put backend secrets in the browser.",
    "launch": "Start finance worker. Confirm heartbeat, one intended-label intake, a real case review and source-linked report in the browser. Follow the event's current approval setting; two-person mode needs two distinct actual members. Confirm live providers and held-out improvement separately; never substitute canned outcomes.",
    "coinbase": "Optional testnet only. Configure the documented Coinbase adapter/network after the core event is working. Keep payment execution blocked until the current event policy's required humans approve the exact current action and the actual provider receipt is verified. Configuration is not a payment check.",
}
ORDER = (
    "model",
    "hermes",
    "supabase_api",
    "database_schema",
    "private_storage",
    "dashboard_auth",
    "scope",
    "token_encryption",
    "gmail_oauth",
    "gmail_connection",
    "jev",
)


def _write_checkpoint(settings: Settings, progress: dict) -> None:
    folder = settings.finance_state_dir
    folder.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.NamedTemporaryFile(
        mode="w", dir=folder, prefix="onboarding-", delete=False
    ) as handle:
        temporary = Path(handle.name)
        os.chmod(temporary, 0o600)
        json.dump(progress, handle, indent=2)
    temporary.replace(folder / "onboarding.json")


class OnboardingTools:
    def __init__(self, settings: Settings):
        self.settings = settings
        self.measurement: dict | None = None
        self._measurement_lock = asyncio.Lock()

    async def measure(self) -> dict:
        from app.setup_checks import doctor

        async with self._measurement_lock:
            if self.measurement is None:
                self.measurement = await doctor(self.settings, live=True)
            return self.measurement

    async def checkpoint(self, measured: dict) -> dict:
        progress = {"checked_at": datetime.now(UTC).isoformat(), **measured}
        durable = False
        if all(
            measured["checks"].get(name, {}).get("status") == "passed"
            for name in ("supabase_api", "database_schema", "scope")
        ):
            from app.storage.supabase import SupabaseClient

            try:
                async with SupabaseClient(
                    self.settings.supabase_url, self.settings.backend_key
                ) as db:
                    await db.rpc(
                        "finance_kernel_call",
                        {
                            "p_organization_id": str(self.settings.organization_id),
                            "p_run_id": str(self.settings.run_id),
                            "p_operation": "set_connection_status",
                            "p_arguments": {
                                "provider": "onboarding",
                                "status": "verified_worker"
                                if measured["ready_for_worker"]
                                else "in_progress",
                                "data": progress,
                                "idempotency_key": "setup:"
                                + hashlib.sha256(
                                    json.dumps(progress, sort_keys=True).encode()
                                ).hexdigest(),
                            },
                        },
                    )
                durable = True
            except Exception:  # noqa: BLE001 -- one failed durable checkpoint stays pending without provider text
                # Do not print provider bodies or connection details. No retry.
                progress["checkpoint_error"] = "supabase_checkpoint_not_saved"
        progress["durable_supabase_checkpoint"] = durable
        _write_checkpoint(self.settings, progress)
        return {
            "status": "checkpoint_saved"
            if durable
            else "bootstrap_checkpoint_saved_remote_pending",
            "durable_supabase_checkpoint": durable,
            "configuration": measured["configuration"],
            "checks": measured["checks"],
        }

    async def call(self, name: str, arguments: dict) -> dict:
        if name == "check_setup":
            return await self.measure()
        if name == "read_setup_step":
            step = arguments.get("step")
            if step not in STEPS:
                return {"steps": list(STEPS)}
            return {"step": step, "instructions": STEPS[step]}
        if name != "record_setup_progress":
            raise ValueError("Onboarding tool not permitted")
        # An improver's requested status is ignored. Only deterministic probe data is saved.
        return await self.checkpoint(await self.measure())


async def onboard(settings: Settings, *, manual: bool = False) -> dict:
    from app.setup_checks import doctor

    readiness = await doctor(settings, live=False)
    missing = [
        name for name in ORDER if readiness["checks"].get(name, {}).get("status") != "passed"
    ]
    tools = OnboardingTools(settings)
    result = {
        "status": "setup_required"
        if any(
            not value
            for key, value in readiness["configuration"].items()
            if key in {"model", "supabase", "jev"}
        )
        else "verification_required",
        "readiness": readiness,
        "next_steps": [{"step": name, "instructions": STEPS[name]} for name in missing],
        "resume": "Rerun finance init after completing the next step; every session rechecks actual state.",
    }
    if (
        manual
        or not readiness["configuration"]["model"]
        or readiness["checks"]["hermes"]["status"] != "passed"
    ):
        result["agent_status"] = (
            "manual_requested"
            if manual
            else "bootstrap_model_access_required"
            if not readiness["configuration"]["model"]
            else "bootstrap_runtime_required"
        )
        result["checkpoint"] = await tools.checkpoint(readiness)
        return result
    from app.models import ModelConfig, ModelError
    from app.runtime.hermes import HermesActor

    try:
        actor = HermesActor(
            ModelConfig.from_settings(settings),
            mode="onboarding",
            max_iterations=6,
            source=Path(settings.finance_hermes_source) if settings.finance_hermes_source else None,
            python=settings.finance_hermes_python or None,
        )
        result["agent"] = await actor.run(
            {
                "request": "Guide the next incomplete setup step. Call check_setup, verify state, never ask for secrets, and never bypass a failed authentication check.",
                "readiness": readiness,
            },
            resource_path("skills/onboarding/SKILL.md").read_text(),
            tools,
        )
        result["agent_status"] = "responded"
        if tools.measurement is not None:
            result["readiness"] = tools.measurement
    except ModelError as error:
        result["agent_status"] = "blocked"
        result["agent_error"] = error.code
    result["checkpoint"] = await tools.checkpoint(tools.measurement or readiness)
    return result
