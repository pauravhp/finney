from __future__ import annotations

import copy
import hashlib
import re
from typing import Any

from app.finance.types import FinanceError, Scope, cash_forecast, minor_units
from app.storage.supabase import SupabaseClient, SupabaseError

READS = {"get_case", "list_due_work", "get_obligations", "get_active_skill", "get_approval_status", "get_payment_status", "get_trace", "get_budget_plan"}
WRITES = {"record_source", "record_case", "record_finding", "propose_obligation_update", "post_ledger",
          "create_approval_request", "reserve_approved_payment", "transition_payment", "confirm_payment",
          "record_trace", "save_skill_version", "record_eval_run", "record_eval_result", "record_promotion",
          "set_active_skill_version", "set_connection_status", "initialize_skill_baseline", "rollback_skill_version", "record_report", "record_case_review",
          "assert_payment_run_authorized", "reserve_run_inference", "claim_improvement_attempt", "claim_improvement_holdout", "finish_improvement_attempt", "record_director_response"}
EVALUATION_WRITES = {"record_trace", "record_eval_run", "record_eval_result"}


class FinanceToolClient:
    """A scope and capability boundary; never pass its private HTTP client to an actor."""

    def __init__(self, scope: Scope, client: SupabaseClient, *, prepare_only: bool = False,
                 snapshot: dict[str, Any] | None = None):
        self.scope, self._client, self.prepare_only = scope, client, prepare_only
        self._snapshot = copy.deepcopy(snapshot) if snapshot is not None else None

    def for_evaluation(self, snapshot: dict[str, Any]) -> FinanceToolClient:
        if str(snapshot.get("run", {}).get("id")) != str(self.scope.run_id) or str(snapshot.get("organization", {}).get("id")) != str(self.scope.organization_id):
            raise FinanceError("evaluation snapshot scope mismatch")
        return FinanceToolClient(self.scope, self._client, prepare_only=True, snapshot=snapshot)

    def _validate_arguments(self, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise FinanceError("tool arguments must be an object")
        if any(key in arguments for key in ("required_approvals", "required_payment_approvals", "approval_policy_version", "p_required_approvals", "p_expected_revision")):
            raise FinanceError("approval policy is controlled by the authenticated event director")
        if any(key in arguments for key in ("organization_id", "run_id", "actor_id", "role", "p_organization_id", "p_run_id")):
            raise FinanceError("tool scope and identity cannot be supplied by actor")

    async def call(self, name: str, arguments: dict[str, Any]) -> Any:
        self._validate_arguments(arguments)
        args = copy.deepcopy(arguments)
        if name == "validate_prepared_decision":
            return self.validate_prepared_decision(args)
        if name in {"get_financial_position", "get_finance_snapshot"}:
            snapshot = self._snapshot or await self._client.rpc("get_finance_snapshot", self.scope.params())
            return copy.deepcopy(snapshot["position"] if name == "get_financial_position" else snapshot)
        if name == "get_budget_plan" and self._snapshot is None:
            return await self._client.rpc("get_finance_budget", self.scope.params())
        if name == "calculate_cash_forecast":
            position = await self.call("get_financial_position", {})
            obligations = await self.call("get_obligations", {})
            return cash_forecast(position["cash_minor"], obligations, currency=position["currency"])
        if name == "simulate_commitment":
            position = await self.call("get_financial_position", {})
            if args.get("currency") != position["currency"]:
                raise FinanceError("commitment currency mismatch")
            amount = minor_units(args.get("amount_minor"), nonnegative=True)
            available = position["available_minor"]
            return {"currency": position["currency"], "available_after_minor": None if available is None else str(minor_units(available)-amount),
                    "status": "unknown_cash" if available is None else "simulation"}
        if name in {"put_artifact", "read_artifact"}:
            if self._snapshot is not None and name == "read_artifact":
                artifacts = self._snapshot.get("artifacts", {})
                if args.get("artifact_path") not in artifacts:
                    raise FinanceError("artifact absent from captured snapshot")
                return {"artifact_path": args["artifact_path"], "content": artifacts[args["artifact_path"]]}
            return await self._artifact(name, args)
        if name == "read_document":
            if self._snapshot is None:
                source_id = args.get("source_id", args.get("document_id"))
                if not source_id:
                    raise FinanceError("source_id required")
                rows = await self._client.select("source_items", filters={"organization_id": f"eq.{self.scope.organization_id}",
                    "run_id": f"eq.{self.scope.run_id}", "id": f"eq.{source_id}"}, limit=1)
                if not rows or not rows[0].get("artifact_path"):
                    raise FinanceError("source document unavailable")
                source = rows[0]
                artifact = await self._artifact("read_artifact", {"artifact_path": source["artifact_path"]})
                return {**source, **artifact}
            for item in self._snapshot.get("source_items", []) + self._snapshot.get("documents", []):
                if str(item.get("id")) == str(args.get("source_id", args.get("document_id"))) and "content" in item:
                    return copy.deepcopy(item)
            raise FinanceError("document text absent from captured snapshot")
        if self._snapshot is not None and name in READS:
            return self._snapshot_read(name, args)
        if name not in READS | WRITES:
            raise FinanceError(f"unsupported finance tool: {name}")
        if self.prepare_only and name in WRITES - EVALUATION_WRITES:
            raise FinanceError(f"prepare-only capability denies {name}")
        if name == "propose_obligation_update":
            if args.get("evidence_status", "reported") not in {"expected", "reported"}:
                raise FinanceError("confirmation requires trusted attestation or provider verification")
            refs = args.get("source_refs")
            if not isinstance(refs, list) or not 1 <= len(refs) <= 200 or any(
                not isinstance(ref, dict) or set(ref) != {"id", "version"}
                or not isinstance(ref["id"], str) or type(ref["version"]) is not int
                or ref["version"] < 1 for ref in refs
            ):
                raise FinanceError("current versioned source references required")
        if name == "record_case_review":
            return await self._client.rpc("record_finance_case_review", {**self.scope.params(),
                "p_case_id":args["case_id"],"p_expected_version":args["expected_version"],
                "p_expected_source_ids":args["expected_source_ids"],"p_trace_id":args["trace_id"],
                "p_job_id":args["job_id"],"p_finding":args["finding"],"p_idempotency_key":args["idempotency_key"]})
        if name == "record_director_response":
            return await self._client.rpc("record_finance_director_response", {**self.scope.params(),
                "p_case_id": args["case_id"], "p_expected_version": args["expected_version"],
                "p_expected_source_ids": args["expected_source_ids"], "p_trace_id": args["trace_id"],
                "p_job_id": args["job_id"], "p_response": args["response"], "p_idempotency_key": args["idempotency_key"]})
        if "proposed_by" in args and name != "create_approval_request":
            raise FinanceError("proposer identity is service-derived")
        if name == "create_approval_request":
            # Human identity is bound by the trusted coordinator, never model text.
            args["proposed_by"] = str(self.scope.actor_id) if self.scope.actor_id else None
        if name in {"post_ledger", "propose_obligation_update"} and "amount_minor" in args:
            args["amount_minor"] = str(minor_units(args["amount_minor"], nonnegative=True))
        return await self._client.rpc("finance_kernel_call", {**self.scope.params(), "p_operation": name, "p_arguments": args})

    def _snapshot_read(self, name: str, args: dict[str, Any]) -> Any:
        assert self._snapshot is not None
        if name == "get_obligations":
            if "obligations" not in self._snapshot:
                raise FinanceError("captured snapshot lacks obligations")
            return copy.deepcopy(self._snapshot["obligations"])
        if name == "get_budget_plan":
            if "budget" not in self._snapshot:
                raise FinanceError("captured snapshot lacks budget")
            return copy.deepcopy(self._snapshot["budget"])
        if name == "list_due_work":
            return copy.deepcopy([c for c in self._snapshot.get("cases", []) if c.get("status") != "closed"])
        if name == "get_case":
            for case in self._snapshot.get("cases", []):
                if str(case.get("id")) == str(args.get("case_id")):
                    return copy.deepcopy(case)
            raise FinanceError("case absent from captured snapshot")
        raise FinanceError("operation unavailable in evaluation snapshot")

    def validate_prepared_decision(self, args: dict[str, Any]) -> dict[str, Any]:
        decision = args.get("decision")
        if not isinstance(decision, dict):
            raise FinanceError("prepared decision object required")
        errors = []
        action = decision.get("action")
        if action not in {"pay_vendor", "reimburse_organizer", "investigate", "no_action"}:
            errors.append("unsupported_decision")
        if any(k in decision for k in ("executed", "provider_reference", "approved", "approval_count")):
            errors.append("decision_cannot_claim_external_effect_or_approval")
        if action in {"pay_vendor", "reimburse_organizer"}:
            try:
                if minor_units(decision.get("amount_minor"), nonnegative=True) == 0:
                    errors.append("payment_amount_must_be_positive")
            except FinanceError:
                errors.append("invalid_amount")
            currency = (self._snapshot or {}).get("position", {}).get("currency")
            if not currency or decision.get("currency") != currency:
                errors.append("currency_not_in_snapshot")
            sources = {(str(s.get("id")), s.get("version")) for s in (self._snapshot or {}).get("source_items", [])}
            refs = decision.get("evidence_refs", [])
            if not refs or any((str(ref.get("id")), ref.get("version")) not in sources for ref in refs):
                errors.append("missing_or_stale_source_reference")
        return {"valid": not errors, "hard_invariants_passed": not errors, "errors": errors, "effects_enabled": False}

    async def _artifact(self, name: str, args: dict[str, Any]) -> dict[str, Any]:
        prefix = f"{self.scope.organization_id}/{self.scope.run_id}/artifacts/"
        if name == "read_artifact":
            path = args.get("artifact_path", "")
            if not isinstance(path, str) or not path.startswith(prefix) or any(part in {".", ".."} for part in path.split("/")):
                raise FinanceError("artifact outside bound run")
            content = await self._client.download("finance-artifacts", path)
            digest = hashlib.sha256(content).hexdigest()
            path_digest = path.split("/")[-2]
            if re.fullmatch(r"[0-9a-f]{64}", path_digest) and digest != path_digest:
                raise FinanceError("artifact content hash mismatch")
            return {"content": content.decode("utf-8"), "artifact_path": path, "content_sha256": digest}
        content = args.get("content")
        if not isinstance(content, str) or len(content.encode("utf-8")) > 10_485_760:
            raise FinanceError("artifact must be UTF-8 text of at most 10 MiB")
        raw = content.encode("utf-8")
        digest = hashlib.sha256(raw).hexdigest()
        filename = re.sub(r"[^a-zA-Z0-9_.-]", "_", str(args.get("name", "artifact.txt")))[:100]
        if filename in {".", "..", ""}:
            raise FinanceError("invalid artifact name")
        path = f"{prefix}{digest}/{filename}"
        try:
            await self._client.upload("finance-artifacts", path, raw, str(args.get("content_type", "text/plain")))
        except SupabaseError as exc:
            if exc.status not in {400, 409}:
                raise
            # A collision is acceptable only if the actual private object matches.
            existing = await self._client.download("finance-artifacts", path)
            if hashlib.sha256(existing).hexdigest() != digest:
                raise FinanceError("artifact collision") from exc
        return {"artifact_path": path, "content_sha256": digest}
