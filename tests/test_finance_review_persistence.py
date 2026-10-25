"""Completion annotation tests with explicit local state fixtures, no providers."""

import copy
from uuid import uuid4

import pytest

from app.finance.review_persistence import persist_actor_review
from app.finance.types import FinanceError


class ReviewFixture:
    def __init__(self):
        self.source_id, self.case_id, self.job_id, self.trace_id = [str(uuid4()) for _ in range(4)]
        self.before = {
            "id": self.case_id,
            "version": 1,
            "status": "open",
            "data": {
                "source_ids": [self.source_id],
                "evidence_state": "reported",
                "keep": "original",
            },
        }
        self.current = copy.deepcopy(self.before)
        self.job = {
            "id": self.job_id,
            "command_type": "review_case",
            "payload": {"case_id": self.case_id},
        }
        self.outcome = {
            "status": "completed",
            "output": {
                "decision": "investigate_missing_payer",
                "evidence_source_ids": [self.source_id],
                "clarification": "Who personally paid this invoice?",
                "proposed_action": None,
                "explanation": "Payer evidence is missing.",
            },
            "tool_events": [],
            "trace": {"id": self.trace_id},
        }
        self.calls = []
        self.race = False

    async def call(self, name, args):
        self.calls.append((name, args))
        if name == "get_trace":
            return {
                "id": self.trace_id,
                "event_type": "actor_completed",
                "payload": {
                    "job_id": self.job_id,
                    "skill_version": "actual-test-skill-id",
                    "output": copy.deepcopy(self.outcome["output"]),
                    "tool_events": copy.deepcopy(self.outcome["tool_events"]),
                },
            }
        if name == "get_case":
            return copy.deepcopy(self.current)
        if name == "get_finance_snapshot":
            return {"source_items": [{"id": self.source_id, "version": 1}]}
        if name == "record_case_review":
            if self.race:
                raise FinanceError("explicit test CAS race")
            assert args["expected_version"] == self.current["version"]
            assert args["expected_source_ids"] == self.current["data"]["source_ids"]
            self.current["data"]["finding"] = copy.deepcopy(args["finding"])
            self.current["version"] += 1
            return {
                "status": "persisted",
                "case_id": self.case_id,
                "version": self.current["version"],
            }
        raise AssertionError("Unexpected operating/financial mutation: " + name)


@pytest.mark.asyncio
async def test_actual_completion_is_annotation_only_with_real_provenance_and_replay():
    fx = ReviewFixture()
    fx.outcome["output"]["approved"] = (
        True  # unsupported top-level assertion cannot become authority
    )
    first = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert first["status"] == "persisted"
    finding = fx.current["data"]["finding"]
    assert (
        finding["decision"] == "investigate_missing_payer" and finding["effects_completed"] is False
    )
    assert (
        finding["verification"] == "unverified_model_recommendation" and "approved" not in finding
    )
    assert finding["provenance"]["actor_trace_id"] == fx.trace_id
    assert finding["provenance"]["skill_version_id"] == "actual-test-skill-id"
    assert (
        fx.current["data"]["evidence_state"] == "reported"
        and fx.current["data"]["keep"] == "original"
    )
    second = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert second["status"] == "already_persisted"
    assert len([name for name, _ in fx.calls if name == "record_case_review"]) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize("change", ["version", "sources"])
async def test_external_case_changes_are_not_silently_rebased(change):
    fx = ReviewFixture()
    if change == "version":
        fx.current["version"] = 2
    else:
        fx.current["data"]["source_ids"] = [str(uuid4())]
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["reason"] == "review_context_changed_requires_new_review"
    assert all(name != "record_case_review" for name, _ in fx.calls)


@pytest.mark.asyncio
async def test_only_successful_same_case_finding_writes_advance_expected_version():
    fx = ReviewFixture()
    fx.current["version"] = 2
    fx.outcome["tool_events"] = [
        {
            "name": "record_finding",
            "arguments": {"case_id": fx.case_id, "expected_version": 1},
            "result": {"case_id": fx.case_id, "version": 2},
        }
    ]
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["status"] == "persisted"
    write = next(args for name, args in fx.calls if name == "record_case_review")
    assert write["expected_version"] == 2
    fx = ReviewFixture()
    fx.current["version"] = 2
    fx.outcome["tool_events"] = [
        {
            "name": "record_finding",
            "arguments": {"case_id": fx.case_id, "expected_version": 1},
            "result": {"status": "failed", "error": "stale"},
        }
    ]
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["status"] == "blocked"


@pytest.mark.asyncio
async def test_unsupported_citation_and_fake_settlement_claim_do_not_persist():
    fx = ReviewFixture()
    fx.outcome["output"]["evidence_source_ids"] = [str(uuid4())]
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["reason"] == "review_citation_outside_scope_or_version"
    fx = ReviewFixture()
    fx.outcome["output"]["proposed_action"] = {
        "action": "pay_vendor",
        "amount_minor": "100",
        "approved": True,
    }
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["reason"] == "unsupported_prepared_review_output"
    assert all(name != "record_case_review" for name, _ in fx.calls)


@pytest.mark.asyncio
async def test_write_cas_race_blocks_without_retrying_against_a_new_version():
    fx = ReviewFixture()
    fx.race = True
    result = await persist_actor_review(fx, fx.before, fx.outcome, fx.job)
    assert result["reason"] == "review_context_or_persistence_changed"
    assert len([name for name, _ in fx.calls if name == "record_case_review"]) == 1
