# Future observability inputs for the improvement loop

**Status: proposal for later implementation.** This document records a possible
additional input to the director-finance self-improvement loop: sanitized
operational and product-friction signals from a telemetry source such as
Datadog, PostHog, or an equivalent. No account, SDK, provider request, integration,
or vendor-specific capability has been verified or implemented.

## Fit with the current engine

The improvement engine starts from an execution trace, uses Jev triage and a
reasoning reviewer to diagnose a supported procedure defect, creates a scoped
skill candidate, then compares baseline and candidate on the protected paired
suite. Its recorded evaluation metrics include tool-call counts, run latency,
provider usage where returned, review/proposal overhead, and the hard promotion
gate. Broader service operations and user friction are not current engine inputs.

The current recorded experiment has **no measured improvement**: offline regrade gave
both variants 3/3 correct with 13 tool calls each; the transfer case did not run,
and the original baseline remained active. Future observability would help find
what to investigate. It does not change that result or establish an improvement.

## Candidate signal families

Keep signals coarse and tied to an explicit event or measured interval. Possible
operational signals include:

- error class and service/tool boundary, provider status class, timeout count,
  retry count, and whether work ended, resumed, or remained blocked;
- queue delay and elapsed time at agent, tool, and approval stages, when those
  boundaries can be measured separately;
- provider-reported token usage or cost when available, with its source and
  coverage recorded; otherwise mark cost unknown rather than estimating silently.

Possible product-friction signals include:

- human corrections, clarifications, handoffs, or repeated attempts, recorded as
  event counts and stage rather than retaining the entered text;
- approval requested, waiting, answered, expired, or cancelled, with timestamps
  sufficient to measure wait duration and whether the wait is still open;
- run abandonment or resume after a documented inactivity interval, reported as
  an incomplete observation when completion cannot be determined.

## Correlation and privacy boundary

Join events through opaque, tenant-scoped organization/run, case, execution trace,
improvement attempt/evaluation, and baseline/candidate version IDs as applicable.
Preserve event time, source, signal definition, and coverage. Include the event
approval-policy count/version; a director changing two approvals to one is a policy
decision and must not be attributed to learned skill improvement. Enforce finance
record access checks; do not create cross-tenant person or session identifiers.

Send allowlisted structured fields only. No raw emails, document text, financial
details or amounts, account identifiers, credentials, model prompts/responses, or
session replay by default. Avoid high-cardinality free text. Link back to scoped
traces under existing access controls; define retention and deletion first.

## Proposed path into self-improvement

1. A later adapter normalizes selected events into versioned, privacy-reviewed
   signal records with provenance and missing-data markers; no raw content enters
   the improver.
2. Aggregate patterns (for example, repeated tool retries or clarifications) to
   prioritize trace review. A signal is a diagnosis lead, not proof of a defect.
3. Require a reviewer to cite a scoped trace and supporting source/tool evidence.
   Only a supported procedure defect can produce a candidate skill edit.
4. Run candidates through the same fixed paired suite, held-out transfer and
   regression cases, hard invariants, and promotion gate. Keep telemetry outcomes
   secondary, with definitions and coverage; they cannot replace correctness
   checks or alter expected answers.
5. Promote or reject through the existing trusted gate. Friction or wait-time
   improvements leave money movement, approval authority, policy, and settlement
   controls unchanged.

## Interpretation limits

- End-to-end latency can include queueing, provider, tool, or approval time.
  Attribute only intervals with known boundaries; label total elapsed time.
- Approval wait is often outside the agent's control. Report it separately from
  agent operating time; a long wait alone is not evidence of agent failure.
- Clicks, retries, views, and approval requests do not prove correct or completed
  work or settlement. Confirm outcomes from authorized state or explicit outcome
  events. Missing events, sampling, and abandonment can bias rates; show coverage,
  denominators, and unknown outcomes.
- Treat vendor costs as provider-reported only when their receipt and units are
  retained. A token count or duration is not a bill.

Before implementation, choose a source and collection boundary, document consent
and retention, define event schema and success outcomes, then validate isolation
with synthetic runs. Reassess privacy and evaluation controls before connection.
