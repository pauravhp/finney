"""Routing/context contracts only; no model/provider execution."""

import hashlib

import pytest

from app.runtime.jobs import DEFAULT_SKILL
from app.runtime.skills import routed_skill_names, runtime_skill_context


@pytest.mark.parametrize(
    "message,required",
    [
        ("Can we afford another commitment in the food budget?", "budget-cash-planning"),
        ("Review this vendor invoice and deposit", "vendor-spend"),
        ("Which sponsor pledge is still outstanding?", "sponsor-receivables"),
        ("Reimburse this personal card expense", "organizer-expenses"),
        ("Export the financial close report", "close-reporting"),
        ("Prepare the winner prize", "prize-fulfillment"),
        ("Check this attendee flight stipend", "attendee-travel"),
    ],
)
def test_financial_tasks_route_to_their_available_procedure(message, required):
    assert required in routed_skill_names("director_message", {"message": message})


def test_forecast_report_and_sponsor_tasks_do_not_optimize_unrelated_expense_skill():
    content = DEFAULT_SKILL.read_text()
    active = {
        "id": "fixture-active",
        "content_sha256": hashlib.sha256(content.encode()).hexdigest(),
    }
    for command, payload in (
        ("refresh_forecast", {}),
        ("generate_report", {}),
        ("director_message", {"message": "Which sponsor receivable is overdue?"}),
    ):
        context, routing, fixed = runtime_skill_context(
            command, payload, None, active_skill=active, active_content=content
        )
        assert "Director finance runtime" in context
        assert routing["improvement_eligible"] is False
        assert routing["mutable_skill_name"] is None and fixed is None
        assert "organizer-expenses" not in {item["name"] for item in routing["runtime_skills"]}


def test_vendor_context_preserves_current_active_artifact_and_reconstructs_exactly():
    active_content = DEFAULT_SKILL.read_text() + "\nExplicit fixture version marker.\n"
    context, routing, fixed = runtime_skill_context(
        "review_case",
        {},
        {"title": "Unpaid vendor invoice", "data": None},
        active_skill={"id": "fixture-promoted"},
        active_content=active_content,
    )
    assert routing["improvement_eligible"] is True
    assert fixed["prefix"] + active_content + fixed["suffix"] == context
    assert hashlib.sha256(context.encode()).hexdigest() == routing["context_sha256"]
    expense = next(
        item for item in routing["runtime_skills"] if item["name"] == "organizer-expenses"
    )
    assert expense["version"] == "fixture-promoted"
    assert expense["content_sha256"] == hashlib.sha256(active_content.encode()).hexdigest()
