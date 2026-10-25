"""Trusted dispatch connects durable jobs to providers and the scoped actor."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, date, datetime, time
from zoneinfo import ZoneInfo

from httpx import HTTPError

from app.config import Settings
from app.connectors.errors import ConnectionRequired, ProviderError
from app.connectors.intake import persist_evidence, sync_gmail
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope, minor_units
from app.storage.supabase import SupabaseClient, SupabaseError


class IntegratedTools:
    """Actor-only surface; privileged dispatcher retains database/connector access."""

    def __init__(
        self, finance: FinanceToolClient, db: SupabaseClient, *, settings: Settings | None = None
    ):
        self.finance, self.db = finance, db
        self.settings = settings

    @property
    def scope(self):
        return self.finance.scope

    async def claim_corpus_holdout(self, *, experiment_id: str, dataset_sha256: str, candidate_sha256: str):
        """Trusted coordinator-only claim; absent from actor tool dispatch/allowlists."""
        return await self.db.rpc("claim_finance_learning_holdout", {
            **self.scope.params(), "p_experiment_id": experiment_id,
            "p_dataset_sha256": dataset_sha256, "p_candidate_sha256": candidate_sha256,
        })

    def for_evaluation(self, snapshot: dict):
        # Evaluations receive only the snapshot-bound kernel, without live intake.
        return self.finance.for_evaluation(snapshot)

    async def call(self, name: str, arguments: dict):
        self.finance._validate_arguments(arguments)
        if name in {"get_budget_plan", "propose_budget_change"}:
            return await self.db.rpc(
                "get_finance_budget" if name == "get_budget_plan" else "propose_finance_budget",
                {**self.scope.params(), **({"p_arguments": arguments} if name == "propose_budget_change" else {})},
            )
        if name == "create_approval_request":
            from app.payments.authorization import assert_payment_run_authorized
            from app.payments.types import NETWORK, PaymentError, build_testnet_payment_action

            action = arguments.get("action", {})
            if (action.get("type"), action.get("currency"), action.get("asset")) != (
                "payment",
                "USD",
                "USDC",
            ):
                raise PaymentError("only_usd_usdc_testnet_payments_supported")
            if action.get("network") not in {NETWORK, "base-sepolia"}:
                raise PaymentError("mainnet_or_unknown_network_denied")
            settings = self.settings if self.settings is not None else Settings()
            if not settings.coinbase_sender_address:
                raise ConnectionRequired(
                    "Configure the event's testnet sender before preparing payment approvals"
                )
            await assert_payment_run_authorized(self.finance, settings)
            exact = build_testnet_payment_action(
                obligation_id=action.get("obligation_id"),
                obligation_version=action.get("obligation_version"),
                amount_minor=action.get("amount_minor"),
                destination=action.get("destination"),
                sender=settings.coinbase_sender_address,
                max_base_units=settings.coinbase_max_test_usdc_base_units,
            )
            # The model prepares this proposal. The initiating director has not
            # thereby submitted or approved it; the configured human approval policy still applies.
            scope = Scope(self.scope.organization_id, self.scope.run_id, actor_id=None)
            return await FinanceToolClient(scope, self.db).call(
                name, {**arguments, "action": {**action, **exact}}
            )
        if name in {"search_finance_mail", "read_thread"}:
            filters = {
                "organization_id": "eq." + str(self.finance.scope.organization_id),
                "run_id": "eq." + str(self.finance.scope.run_id),
                "source_type": "eq.gmail",
                "order": "created_at.desc",
            }
            if name == "read_thread":
                thread_id = str(arguments.get("thread_id", ""))
                if not thread_id.isalnum():
                    raise ValueError("Gmail thread identity required")
                filters["metadata->>thread_id"] = "eq." + thread_id
            rows = await self.db.select("source_items", filters=filters, limit=50)
            query = str(arguments.get("query", "")).casefold()
            if name == "search_finance_mail":
                # Search only already-intaken authorized evidence, never raw inbox.
                return {
                    "sources": [r for r in rows if query in str(r.get("metadata", {})).casefold()],
                    "scope": "imported_finance_evidence",
                    "limit": 50,
                }
            return {
                "documents": [
                    await self.finance.call("read_document", {"source_id": row["id"]})
                    for row in rows
                ]
            }
        if name in {"generate_financial_report", "export_evidence_pack"}:
            return {
                "status": "prepared",
                "effects_completed": False,
                "snapshot": await self.finance.call("get_finance_snapshot", {}),
                "next_step": "Queue generate_report to persist the report artifact",
            }
        return await self.finance.call(name, arguments)


async def queue_case_review(db: SupabaseClient, job: dict, case_id: str, source_id: str, *, review_key: str | None = None) -> str:
    key = "review-source:" + (review_key or source_id)
    filters = {
        "organization_id": "eq." + job["organization_id"],
        "run_id": "eq." + job["run_id"],
        "idempotency_key": "eq." + key,
    }
    existing = await db.select("jobs", filters=filters, limit=1)
    if existing:
        return existing[0]["id"]
    values = {
        "organization_id": job["organization_id"],
        "run_id": job["run_id"],
        "command_type": "review_case",
        "payload": {"case_id": case_id, "source_id": source_id},
        "requested_by": job.get("requested_by"),
        "idempotency_key": key,
    }
    try:
        rows = await db.insert("jobs", values)
        return rows[0]["id"]
    except SupabaseError as error:
        if error.status != 409:
            raise
        existing = await db.select("jobs", filters=filters, limit=1)
        if not existing or existing[0]["payload"] != values["payload"]:
            raise
        return existing[0]["id"]


async def dispatch_job(
    settings: Settings, job: dict, tools: FinanceToolClient, db: SupabaseClient
) -> dict:
    command, payload = job.get("command_type"), job.get("payload", {})
    try:
        if command == "intake":
            if payload.get("source") == "opening_snapshot":
                actor_id = job.get("requested_by")
                if not actor_id:
                    return {"status": "blocked", "reason": "authenticated_director_required"}
                members = await db.select(
                    "memberships",
                    filters={
                        "organization_id": "eq." + job["organization_id"],
                        "user_id": "eq." + actor_id,
                        "role": "eq.director",
                        "active": "eq.true",
                    },
                    limit=1,
                )
                if not members or payload.get("attested") is not True:
                    return {"status": "blocked", "reason": "director_attestation_required"}
                amount = str(minor_units(payload.get("amount_minor"), nonnegative=True))
                currency = str(payload.get("currency", ""))
                as_of_text = str(payload.get("as_of", ""))
                if len(as_of_text) == 10:
                    as_of = datetime.combine(
                        date.fromisoformat(as_of_text),
                        time.min,
                        ZoneInfo(settings.finance_event_timezone),
                    )
                else:
                    as_of = datetime.fromisoformat(as_of_text)
                if as_of.tzinfo is None or as_of > datetime.now(UTC):
                    raise ValueError(
                        "Opening snapshot needs a past/current timestamp with timezone"
                    )
                metadata = {
                    "evidence_status": "owner_attested",
                    "attested_by": actor_id,
                    "amount_minor": amount,
                    "currency": currency,
                    "as_of": as_of.isoformat(),
                }
                note = str(payload.get("note", ""))
                if not note.strip() or len(note) > 4000:
                    raise ValueError("An opening balance evidence note is required")
                content = json.dumps(
                    {
                        **metadata,
                        "note": note,
                        "meaning": "Director-attested opening cash; not independently bank-verified",
                    },
                    sort_keys=True,
                )
                artifact = await tools.call(
                    "put_artifact",
                    {
                        "name": "opening-cash-attestation.json",
                        "content": content,
                        "content_type": "application/json",
                    },
                )
                source = await tools.call(
                    "record_source",
                    {
                        "external_id": "opening:" + job["id"],
                        "version": 1,
                        "source_type": "owner_attestation",
                        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
                        "artifact_path": artifact["artifact_path"],
                        "metadata": metadata,
                        "idempotency_key": "opening-source:" + job["id"],
                    },
                )
                recorded = await db.rpc(
                    "establish_finance_opening_cash",
                    {
                        "p_organization_id": job["organization_id"],
                        "p_run_id": job["run_id"],
                        "p_actor_id": actor_id,
                        "p_amount_minor": amount,
                        "p_currency": currency,
                        "p_as_of": as_of.isoformat(),
                        "p_evidence_source_id": source["id"],
                        "p_idempotency_key": "opening:" + job["id"],
                    },
                )
                return {"status": "completed", "opening_snapshot": recorded}
            if payload.get("source") == "x402":
                from app.payments.authorization import assert_payment_run_authorized
                from app.payments.x402_server import reconcile_configured_income

                await assert_payment_run_authorized(tools, settings)
                return await reconcile_configured_income(tools, db, payload)
            queued = []

            async def ensure_review(item: dict) -> None:
                if item.get("case_id"):
                    queued.append(
                        await queue_case_review(db, job, item["case_id"], item["source_id"], review_key=item.get("review_key"))
                    )

            if payload.get("source") == "demo_bundle":
                from app.demo import seed_demo_bundle

                outcome = await seed_demo_bundle(settings, tools, db, job)
                for item in outcome["source_results"]:
                    if item.get("review_required"):
                        await ensure_review(item)
            elif payload.get("source") == "manual":
                from app.finance.workflows import manual_evidence, require_event_editor

                await require_event_editor(db, job)
                item = await persist_evidence(tools, db, manual_evidence(payload, job))
                await ensure_review(item)
                outcome = {"status": "completed", "source_results": [item]}
            elif payload.get("source") == "upload":
                from app.finance.workflows import ingest_uploaded_document

                item = await ingest_uploaded_document(settings, tools, db, payload, job)
                await ensure_review(item)
                outcome = {"status": "completed", "source_results": [item]}
            elif payload.get("source", "gmail") == "csv":
                from app.imports.csv_records import parse_finance_csv

                content = payload.get("content", "")
                if not isinstance(content, str) or len(content.encode()) > 5_000_000:
                    raise ValueError("CSV input exceeds intake limit")
                rows = parse_finance_csv(content, currency=payload.get("currency", ""))
                results = [await persist_evidence(tools, db, row) for row in rows]
                for item in results:
                    await ensure_review(item)
                outcome = {"status": "completed", "source_results": results}
            elif payload.get("source", "gmail") == "gmail":
                outcome = await sync_gmail(settings, tools, db, on_source=ensure_review)
            else:
                raise ValueError("Unsupported intake source")
            return {**outcome, "review_jobs": queued}
        if command == "refresh_forecast":
            forecast = await tools.call("calculate_cash_forecast", {})
            await tools.call(
                "record_trace",
                {
                    "event_type": "forecast_refreshed",
                    "payload": forecast,
                    "idempotency_key": "forecast:" + job["id"],
                },
            )
            return {"status": "completed", "forecast": forecast}
        if command == "generate_report":
            from app.finance.workflows import build_close_report

            snapshot = await tools.call("get_finance_snapshot", {})
            obligations = await tools.call("get_obligations", {})
            cutoff = snapshot.get("updated_at") or datetime.now(UTC).isoformat()
            report = build_close_report(snapshot, obligations, cutoff=cutoff)
            artifact = await tools.call(
                "put_artifact",
                {
                    "name": "finance-close-report.json",
                    "content": json.dumps(report, sort_keys=True),
                    "content_type": "application/json",
                },
            )
            record = await tools.call(
                "record_report",
                {
                    "cutoff": cutoff,
                    "data": report,
                    "artifact_path": artifact["artifact_path"],
                    "idempotency_key": "report:" + job["id"],
                },
            )
            return {
                "status": "completed",
                "report": record,
                "artifact_path": artifact["artifact_path"],
            }
        if command == "execute_payment":
            from app.payments.executor import execute_configured_payment

            return await execute_configured_payment(tools, str(payload.get("proposal_id", "")), settings=settings)
        from app.runtime.jobs import run_job

        if command == "director_message":
            from app.finance.workflows import persist_director_message

            message_case = await persist_director_message(tools, db, job)
            job = {**job, "payload": {**payload, **message_case}}
            payload = job["payload"]
            updated = await db.update("jobs", {"payload": payload}, filters={
                "organization_id": "eq." + job["organization_id"], "run_id": "eq." + job["run_id"],
                "id": "eq." + job["id"], "status": "eq.running",
                "lease_token": "eq." + str(job["lease_token"]),
            })
            if len(updated) != 1:
                raise ValueError("director_message_lease_changed")
        before_case = None
        if command in {"review_case", "director_message"} and payload.get("case_id"):
            before_case = await tools.call("get_case", {"case_id": payload["case_id"]})
        outcome = await run_job(
            job, IntegratedTools(tools, db, settings=settings), settings=settings
        )
        if command in {"review_case", "director_message"} and outcome.get("status") == "completed":
            if command == "director_message":
                from app.finance.director_response import persist_director_response

                prepared = await persist_director_response(tools, before_case, outcome, job)
                outcome["director_response"] = prepared
            else:
                from app.finance.review_persistence import persist_actor_review

                prepared = await persist_actor_review(tools, before_case, outcome, job)
                outcome["case_review"] = prepared
            if prepared.get("status") == "blocked":
                outcome.update(
                    {"status": "blocked", "actor_status": "completed", "reason": prepared["reason"]}
                )
            from app.finance.workflows import queue_automatic_improvement

            outcome["automatic_improvement"] = await queue_automatic_improvement(
                db, job, outcome,
                **({"suite_id": "organizer-expenses-promotion-v1"}
                   if settings.finance_improvement_method == "harness2" else {}),
            )
        elif command == "review_case" and outcome.get("improvement_eligible") is True:
            from app.finance.workflows import queue_automatic_improvement

            outcome["automatic_improvement"] = await queue_automatic_improvement(
                db, job, outcome,
                **({"suite_id": "organizer-expenses-promotion-v1"}
                   if settings.finance_improvement_method == "harness2" else {}),
            )
        return outcome
    except ConnectionRequired:
        return {"status": "blocked", "reason": "connector_authorization_required"}
    except ProviderError as error:
        health_error = None
        if error.provider in {"gmail", "google_oauth"}:
            status = "reconnect_required" if error.status in {400, 401, 403} else "degraded"
            try:
                await tools.call(
                    "set_connection_status",
                    {
                        "provider": "gmail",
                        "status": status,
                        "data": {
                            "last_error_type": error.provider,
                            "last_http_status": error.status,
                        },
                        "idempotency_key": f"gmail-health:{job['id']}:{error.provider}:{error.status}",
                    },
                )
            except (SupabaseError, HTTPError) as persistence_error:
                health_error = type(persistence_error).__name__
        return {
            "status": "blocked",
            "reason": "provider_request_failed",
            "provider": error.provider,
            "provider_status": error.status,
            "retryable": error.retryable,
            "health_persistence_error": health_error,
        }
