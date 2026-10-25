"""Director-only Gmail consent endpoints, separate from dashboard Supabase Auth."""

from __future__ import annotations

import hashlib
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from uuid import UUID

import httpx
from fastapi import FastAPI, Header, HTTPException
from fastapi.responses import HTMLResponse
from pydantic import BaseModel

from app.config import Settings
from app.storage.supabase import SupabaseClient

from .gmail import GmailClient, GmailOAuth
from .tokens import TokenCipher


class StartRequest(BaseModel):
    organization_id: UUID
    run_id: UUID


def create_app() -> FastAPI:
    resources = []

    @asynccontextmanager
    async def lifespan(_app):
        try:
            yield
        finally:
            for resource in resources:
                await resource.close()

    app = FastAPI(title="Director Finance connectors", lifespan=lifespan)
    settings = Settings()

    @app.middleware("http")
    async def private_responses(request, call_next):
        if request.url.path.startswith("/x402/") and request.url.path != "/x402/health" and recorder is not None:
            from fastapi.responses import JSONResponse

            from app.payments.authorization import assert_payment_run_authorized
            from app.payments.types import PaymentError, address

            try:
                if address(payment_config.pay_to_address) != address(settings.coinbase_sender_address):
                    raise PaymentError("x402_recipient_must_match_configured_event_wallet")
                await assert_payment_run_authorized(finance, settings)
            except Exception:  # noqa: BLE001 -- deny before the facilitator can perform any payment effect
                return JSONResponse({"status": "blocked", "reason": "private_event_payment_binding_required"}, status_code=503,
                                    headers={"Cache-Control": "no-store"})
        response = await call_next(request)
        response.headers["Cache-Control"] = "no-store"
        response.headers["Pragma"] = "no-cache"
        response.headers["Referrer-Policy"] = "no-referrer"
        return response

    def configured():
        if settings.finance_gmail_backend == "hermes":
            raise HTTPException(409, "Connect the isolated Hermes mailbox with finance gmail-connect on the worker host")
        if not all(
            settings.configured()[key] for key in ("supabase", "gmail_oauth", "token_encryption")
        ):
            raise HTTPException(503, "Mailbox connector configuration required")

    @app.post("/oauth/gmail/start")
    async def start(body: StartRequest, authorization: str = Header(default="")):
        configured()
        if not authorization.startswith("Bearer "):
            raise HTTPException(401, "Sign in to the dashboard first")
        async with httpx.AsyncClient(timeout=20, follow_redirects=False) as http:
            auth = await http.get(
                settings.supabase_url.rstrip("/") + "/auth/v1/user",
                headers={
                    "apikey": settings.supabase_publishable_key,
                    "Authorization": authorization,
                },
            )
            if auth.status_code != 200:
                raise HTTPException(401, "Dashboard session is invalid")
            user_id = auth.json()["id"]
        org, run = str(body.organization_id), str(body.run_id)
        async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
            members = await db.select(
                "memberships",
                filters={
                    "organization_id": "eq." + org,
                    "user_id": "eq." + user_id,
                    "role": "eq.director",
                    "active": "eq.true",
                },
            )
            runs = await db.select(
                "demo_runs",
                filters={"organization_id": "eq." + org, "id": "eq." + run, "status": "eq.active"},
            )
            if not members or not runs:
                raise HTTPException(
                    403, "Only an authorized director can connect this event mailbox"
                )
            # A real personal mailbox may not be attached to an anonymous public demo.
            if runs[0]["is_demo"]:
                raise HTTPException(403, "Use a private event run for a personal mailbox")
            attempt = GmailOAuth(
                settings.google_client_id,
                settings.google_client_secret.get_secret_value(),
                settings.google_redirect_uri,
            ).begin()
            digest = hashlib.sha256(attempt.state.encode()).hexdigest()
            cipher = TokenCipher(settings.finance_token_encryption_key.get_secret_value())
            await db.insert(
                "oauth_pending",
                {
                    "state_hash": digest,
                    "organization_id": org,
                    "run_id": run,
                    "provider": "gmail",
                    "user_id": user_id,
                    "encrypted_verifier": cipher.seal(
                        {"verifier": attempt.verifier}, organization_id=org, connection_id=digest
                    ),
                    "redirect_uri": settings.google_redirect_uri,
                    "expires_at": (datetime.now(UTC) + timedelta(minutes=10)).isoformat(),
                },
            )
            return {"authorization_url": attempt.authorization_url}

    @app.get("/oauth/gmail/callback", response_class=HTMLResponse)
    async def callback(state: str = "", code: str = "", error: str = ""):
        configured()
        if error or not state or not code:
            raise HTTPException(400, "Mailbox authorization was not completed")
        digest = hashlib.sha256(state.encode()).hexdigest()
        now = datetime.now(UTC).isoformat()
        async with SupabaseClient(settings.supabase_url, settings.backend_key) as db:
            # Conditional update is the single-use consume operation. Concurrent
            # callbacks cannot both obtain a still-valid authorization attempt.
            pending = await db.update(
                "oauth_pending",
                {"expires_at": "1970-01-01T00:00:00+00:00"},
                filters={
                    "state_hash": "eq." + digest,
                    "provider": "eq.gmail",
                    "expires_at": "gt." + now,
                },
            )
            if len(pending) != 1:
                raise HTTPException(400, "Authorization expired or was already used; reconnect")
            attempt = pending[0]
            if attempt["redirect_uri"] != settings.google_redirect_uri:
                raise HTTPException(400, "Authorization callback configuration changed")
            org, run = attempt["organization_id"], attempt["run_id"]
            members = await db.select(
                "memberships",
                filters={
                    "organization_id": "eq." + org,
                    "user_id": "eq." + attempt["user_id"],
                    "role": "eq.director",
                    "active": "eq.true",
                },
            )
            if not members:
                raise HTTPException(403, "Director authorization was removed")
            runs = await db.select(
                "demo_runs",
                filters={
                    "organization_id": "eq." + org,
                    "id": "eq." + run,
                    "status": "eq.active",
                    "is_demo": "eq.false",
                },
            )
            if not runs or (
                runs[0].get("expires_at")
                and datetime.fromisoformat(runs[0]["expires_at"]) <= datetime.now(UTC)
            ):
                raise HTTPException(403, "The private event run is no longer active")
            cipher = TokenCipher(settings.finance_token_encryption_key.get_secret_value())
            verifier = cipher.open(
                attempt["encrypted_verifier"], organization_id=org, connection_id=digest
            )["verifier"]
            oauth = GmailOAuth(
                settings.google_client_id,
                settings.google_client_secret.get_secret_value(),
                settings.google_redirect_uri,
            )
            async with httpx.AsyncClient(timeout=30, follow_redirects=False) as http:
                tokens = await oauth.exchange(http, code=code, verifier=verifier)
                if not tokens.get("refresh_token"):
                    raise HTTPException(400, "Offline mailbox access was not granted; reconnect")
                profile = await GmailClient(http, tokens["access_token"]).profile()
            connection_id = f"{run}:gmail"
            encrypted = cipher.seal(tokens, organization_id=org, connection_id=connection_id)
            await db.insert(
                "connector_secrets",
                {
                    "organization_id": org,
                    "run_id": run,
                    "provider": "gmail",
                    "encrypted_token": encrypted,
                },
                upsert=True,
                on_conflict="organization_id,run_id,provider",
            )
            await db.rpc(
                "finance_kernel_call",
                {
                    "p_organization_id": org,
                    "p_run_id": run,
                    "p_operation": "set_connection_status",
                    "p_arguments": {
                        "provider": "gmail",
                        "status": "connected",
                        "data": {
                            "mailbox": profile["emailAddress"],
                            "query": settings.finance_gmail_query,
                            "history_id": None,
                            "label_id": None,
                            "mailbox_scope": None,
                            "last_intake_count": 0,
                            "connected_by": attempt["user_id"],
                            "scopes": ["gmail.readonly"],
                            "auth_backend": "api",
                        },
                        "idempotency_key": "gmail-connected:" + digest,
                    },
                },
            )
        return "<!doctype html><title>Mailbox connected</title><h1>Mailbox connected</h1><p>Return to your finance dashboard. Intake is limited to the configured finance label.</p>"

    from app.finance.tools import FinanceToolClient
    from app.finance.types import Scope
    from app.payments.chain import BaseSepoliaVerifier
    from app.payments.x402_server import X402Config, X402SettlementRecorder, create_x402_app

    payment_config = X402Config(
        settings.x402_pay_to_address or None,
        settings.x402_price_base_units,
        settings.x402_facilitator_url,
    )
    recorder = None
    if (
        payment_config.pay_to_address
        and settings.configured()["supabase"]
        and settings.configured()["scope"]
    ):
        database = SupabaseClient(settings.supabase_url, settings.backend_key)
        verifier = BaseSepoliaVerifier(settings.base_sepolia_rpc_url)
        resources.extend([database, verifier])
        finance = FinanceToolClient(Scope(settings.organization_id, settings.run_id), database)
        recorder = X402SettlementRecorder(finance, database, verifier, payment_config)

    async def safe_sponsor_resource():
        # A fixed, deliberately public demo package; no director snapshot,
        # claimant identity, mailbox content or private document is exposed.
        return {
            "package": "testnet-supporter-report-v1",
            "purpose": "Hackathon finance test-organization sponsorship demonstration",
            "testnet_only": True,
            "accounting": "Funding is credited only after independent chain verification",
        }

    app.mount(
        "/x402",
        create_x402_app(
            payment_config,
            recorder=recorder,
            resource_provider=safe_sponsor_resource,
            mount_path="/x402",
        ),
    )
    return app
