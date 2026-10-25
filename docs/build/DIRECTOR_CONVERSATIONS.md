# Director replies are conversations, not forced financial decisions

`director_message` now has the explicit output contract
`finance-director-response-v1`. The actor's actual final reply is retained as
text, including normal Markdown. The adapter wraps it with:

```json
{
  "response_type": "director_response",
  "message": "The actual final response, unchanged",
  "evidence_source_ids": [],
  "consulted_source_refs": []
}
```

Message length is 1–16,000 characters with non-whitespace content. This wrapper
does not invent a financial classification, proposed action, approval or balance.
Explicit finance tools retain their existing structured contracts and protected
authority. A sentence, Markdown table or JSON-looking text in a reply is never
interpreted as a financial write or human approval.

The two source arrays come from actual successful `read_document` results or
document rows in successful `read_thread` results, not from names or citation
strings the model places in its answer. Failed/blocked/error reads are excluded;
IDs and integer versions are validated, deduplicated and ordered. They are
labeled **consulted**: they show what the actor retrieved and do not prove that
each source was cited, supports every sentence, or reflects a confirmed payment.
A reply based only on recorded position/obligation tools can have an empty
consulted-document list. Historical versions may be consulted where their exact
immutable ID/version exists in the same run; this label does not grant them
current financial authority.

## Persistence contract

The trusted dispatcher calls
`persist_director_response(tools, before_case, outcome, job)`. It requires a
completed actual `director_message` trace, exact stored output/tool-event equality,
the new output-contract version, a persisted skill/context identity, and
`improvement_eligible=false`. It reconstructs consulted references independently,
checks scoped source versions and the current case version/source vector, then
calls trusted `record_director_response`. The actor cannot call that operation.

The RPC is:

```text
record_finance_director_response(
  p_organization_id uuid, p_run_id uuid, p_case_id uuid,
  p_expected_version integer, p_expected_source_ids uuid[],
  p_trace_id uuid, p_job_id uuid, p_response jsonb,
  p_idempotency_key text
) returns jsonb
```

The idempotency key is `director-response:<job UUID>`. Migration 015 independently
checks the actual scoped job is a running/completed `director_message`, its
current case payload, current director/finance membership, demo ownership when
applicable, actual completed trace/contract and the exact emitted message. It
derives consulted sources again from the persisted successful tool events and
rejects invented, omitted, duplicate, foreign or wrong-version references.

The RPC appends one entry to `case.data.director_responses` with stable id/job/trace,
actual message, consulted IDs/versions and provenance. It preserves the existing
financial `finding`, case status and other case data. The case version advances
under CAS; external source/version changes block rather than silently rebasing.
An exact replay returns the original result without another entry, while a
changed replay conflicts. Current editor authority is rechecked even for a
replay. Audit/trace records link the actual response without interpreting prose.
The UI must render response text as text or safely escaped Markdown; stored HTML
is not execution authority.

Director replies do not enter the organizer-procedure improvement loop. Existing
`review_case` finance-decision evaluation, protected expected answers, approval
policy, payment service and frozen learning context remain separate and unchanged.

## Local verification and historical limits

The targeted test set passed 57 tests: 24 new conversation tests plus existing
review-persistence and kernel checks, using actual isolated PostgreSQL with
migration 015. Declared local response/Storage fixtures make no provider calls.
Tests cover plain Markdown/HTML-containing text preservation, sequential append,
replay, financial finding/closed-status preservation, no financial mutations,
successful-thread deduplication, empty consulted lists, CAS/source changes,
invented/failed/foreign/wrong-version reads, wrong contracts/commands, cancelled
jobs, public owner mismatch, revoked authority, and browser/evaluation denial.
Ruff passed. Hosted migration and actual form acceptance remain coordinator work
at the time this entry is written; no live calls were made for this implementation.

The earlier actual director-message failures and the successful linked
`review_case` remain historical records. A successful review-case command is not
a successful director-message path. Replacing the inappropriate response-schema
requirement is an application architecture fix, not learned skill improvement,
and does not retroactively complete those failed jobs or create a promotion.
