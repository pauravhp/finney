"""Deterministic task context; routing changes no capabilities or authority."""

from __future__ import annotations

import hashlib
from typing import Any

from app.resources import resource_path

TASK_WORDS = {
    "budget-cash-planning": ("budget", "cash", "forecast", "afford", "allocate", "allocation"),
    "vendor-spend": ("vendor", "supplier", "invoice", "purchase", "catering", "venue", "quote"),
    "sponsor-receivables": ("sponsor", "receivable", "pledge", "sponsorship"),
    "organizer-expenses": ("reimburse", "expense", "personal card", "personally", "out of pocket"),
    "close-reporting": ("report", "reconcile", "reconciliation", "statement", "export", "close"),
    "prize-fulfillment": ("prize", "award", "winner"),
    "attendee-travel": ("travel", "flight", "hotel", "attendee", "stipend"),
}


def routed_skill_names(command: str, payload: dict, case: dict | None = None) -> tuple[str, ...]:
    if command == "refresh_forecast":
        return ("budget-cash-planning",)
    if command == "generate_report":
        return ("close-reporting",)
    case = case or {}
    data = case.get("data") if isinstance(case.get("data"), dict) else {}
    text = " ".join(
        str(value)
        for value in (
            payload.get("message", ""),
            case.get("title", ""),
            case.get("description", ""),
            data.get("workflow", ""),
        )
    ).lower()
    selected = [name for name, words in TASK_WORDS.items() if any(word in text for word in words)]
    if "vendor-spend" in selected and "organizer-expenses" not in selected:
        selected.append("organizer-expenses")
    if not selected and command in {"review_case", "director_message"}:
        selected = ["organizer-expenses", "vendor-spend"]
    return tuple(selected)


def runtime_skill_context(
    command: str, payload: dict, case: dict | None, *, active_skill: dict, active_content: str
) -> tuple[str, dict[str, Any], dict[str, str] | None]:
    names = ("runtime-guide",) + routed_skill_names(command, payload, case)
    parts, manifests = [], []
    for name in names:
        if name == "organizer-expenses":
            content, version = active_content, active_skill["id"]
        else:
            content = resource_path(f"skills/finance/{name}.md").read_text()
            version = "guide-v1" if name == "runtime-guide" else "bundled-v1"
        parts.append(content)
        manifests.append(
            {
                "name": name,
                "version": version,
                "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
            }
        )
    eligible = "organizer-expenses" in names
    fixed = None
    if eligible:
        index = names.index("organizer-expenses")
        before, after = parts[:index], parts[index + 1 :]
        fixed = {
            "prefix": "\n\n".join(before) + ("\n\n" if before else ""),
            "suffix": ("\n\n" if after else "") + "\n\n".join(after),
            "active_skill_sha256": hashlib.sha256(active_content.encode()).hexdigest(),
        }
    return (
        "\n\n".join(parts),
        {
            "runtime_skills": manifests,
            "improvement_eligible": eligible,
            "mutable_skill_name": "organizer-expenses" if eligible else None,
            "routing_version": "finance-task-routing-v1",
            "context_sha256": hashlib.sha256("\n\n".join(parts).encode()).hexdigest(),
        },
        fixed,
    )
