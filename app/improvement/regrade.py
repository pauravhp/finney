"""Regrade a local captured receipt without inference, cloud writes or promotion.

This produces a separate diagnostic artifact. It cannot replace the original
receipt or change any historical database record.
"""

from __future__ import annotations

import argparse
import copy
import hashlib
import json
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from app.finance.tools import FinanceToolClient
from app.finance.types import Scope

from .blockers import BLOCKER_SUITE_ID
from .decisions import EVALUATOR_VERSION
from .engine import _matches, promotion_gate
from .suites import organizer_expense_suite


async def regrade_captured_receipt(path: Path) -> dict:
    raw = path.read_bytes()
    receipt = json.loads(raw)
    job = receipt["job"]
    original = receipt["outcome"]["improvement"]
    # No backend is attached. Every verifier operation is bound to the captured
    # synthetic snapshot and uses the actual local finance kernel validator.
    tools = FinanceToolClient(Scope(UUID(job["organization_id"]), UUID(job["run_id"])), None)
    suite = organizer_expense_suite(tools, BLOCKER_SUITE_ID)
    suite.validate()
    cases = {case.case_key: case for case in suite.cases}
    corrected, changes = [], []
    for index, row in enumerate(original["rows"]):
        case = cases[row["case_key"]]
        if row["details"]["source_snapshot_hash"] != case.source_snapshot_hash:
            raise ValueError("captured_snapshot_hash_mismatch")
        result = row["details"]["result"]
        verified = await suite.verify(case, result)
        passed = bool(
            verified["passed"]
            and verified.get("correctness_checks_passed", True)
            and _matches(case.expected, verified.get("normalized_output", result["output"]))
        )
        corrected.append(
            {
                "case_key": row["case_key"],
                "variant": row["variant"],
                "passed": passed,
                "hard_invariants_passed": verified["passed"],
                "metrics": copy.deepcopy(row["metrics"]),
                "details": {"group": case.group, "evaluator_version": EVALUATOR_VERSION},
            }
        )
        changes.append(
            {
                "case_key": row["case_key"],
                "variant": row["variant"],
                "original_row_pointer": f"/outcome/improvement/rows/{index}",
                "captured_output_sha256": hashlib.sha256(
                    json.dumps(result["output"], sort_keys=True).encode()
                ).hexdigest(),
                "source_snapshot_hash": case.source_snapshot_hash,
                "original_passed": row["passed"],
                "original_hard_invariants_passed": row["hard_invariants_passed"],
                "original_errors": row["details"]["invariants"].get("errors", []),
                "original_blocker_errors": row["details"]["invariants"]
                .get("blocker_checks", {})
                .get("errors", []),
                "corrected_passed": passed,
                "corrected_verification": verified,
            }
        )
    passed, reason, metrics = promotion_gate(corrected)
    captured_cases = {row["case_key"] for row in corrected}
    missing = sorted(set(cases) - captured_cases)
    if path.read_bytes() != raw:
        raise ValueError("original_receipt_changed_during_regrade")
    return {
        "checked_at": datetime.now(UTC).isoformat(),
        "execution": "offline_diagnostic_only",
        "fresh_inference": False,
        "provider_calls": 0,
        "cloud_operations": 0,
        "promotion_permitted": False,
        "original_receipt": str(path),
        "original_receipt_sha256": hashlib.sha256(raw).hexdigest(),
        "original_attempt_id": original["attempt_id"],
        "original_suite_id": original["suite_id"],
        "corrected_suite_id": suite.suite_id,
        "evaluator_version": EVALUATOR_VERSION,
        "original_outcome": {
            "status": original["status"],
            "reason": original["reason"],
            "metrics": original["metrics"],
        },
        "corrected_diagnostic": {
            "measured_improvement_gate_passed": passed,
            "reason": reason,
            "metrics": metrics,
            "all_captured_snapshot_hashes_match": True,
            "captured_case_count": len(captured_cases),
            "suite_case_count": len(cases),
            "unexecuted_cases": missing,
            "unseen_transfer_executed": not any(cases[key].group == "transfer" for key in missing),
        },
        "rows": changes,
        "limitations": [
            "This reuses captured live outputs; it is not a fresh paired inference run.",
            "No original score, historical outcome, skill activation or promotion record was changed.",
            "Cases not captured in the original attempt were not executed or graded.",
        ],
    }


def main() -> None:
    import asyncio

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("receipt", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args()
    if arguments.output.resolve() == arguments.receipt.resolve():
        raise ValueError("diagnostic_must_not_replace_receipt")
    result = asyncio.run(regrade_captured_receipt(arguments.receipt))
    with arguments.output.open("x") as output:
        output.write(json.dumps(result, indent=2) + "\n")
    print(json.dumps({"artifact": str(arguments.output), **result["corrected_diagnostic"]}))


if __name__ == "__main__":
    main()
