"""Fixed actor-visible explanations for known finance-kernel rejections only."""
from __future__ import annotations

from app.storage.supabase import SupabaseError

_GUIDANCE = {
    "source_reference_not_current": (
        "The database rejected a source reference because it is missing, superseded, or outside this run. "
        "Re-read the case and its current documents. Use only current, in-scope source IDs and versions "
        "for the financial update; keep older documents as history, not operative evidence. "
        "Do not retry the unchanged references or claim the update succeeded."
    ),
    "source_references_required": (
        "This financial update requires current source IDs and versions. Read the supporting documents "
        "and provide source_refs; do not invent evidence or claim the update succeeded."
    ),
    "source_references_invalid": (
        "The source_refs structure is invalid. Supply current in-scope source IDs and positive integer "
        "versions from the document tools; do not invent references or claim the update succeeded."
    ),
}


def safe_tool_failure(error: Exception) -> dict:
    result = {"status": "failed", "error": "finance_tool_error", "error_type": type(error).__name__}
    reason = error.domain_reason if isinstance(error, SupabaseError) else None
    if reason in _GUIDANCE and error.status == 400:
        result.update(error="finance_domain_rejection", reason=reason,
                      explanation=_GUIDANCE[reason], retry_unchanged=False)
    return result
