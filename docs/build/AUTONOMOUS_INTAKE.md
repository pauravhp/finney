# Autonomous intake, wake checks and director prompts

Finney autonomously discovers new messages in the connected event finance label
while its worker is running, imports their evidence and attachments, and queues
agent reviews. The director can also submit a finance request in the app at any
time. These are ordinary operating paths, separate from learning experiments.

## Mail and wake behavior

- The existing scheduler runs immediately on worker startup, then checks eligible
  connected mailboxes every 60 seconds. It verifies a current director, active
  private event and configured finance label before queueing intake. Discovery
  continues while a model job is running; source processing waits for a lease.
- Gmail intake uses the saved history cursor. Messages arriving while the worker
  was stopped are caught on restart. Missing or expired history triggers a bounded
  rescan of the selected label. The cursor advances only after sources, attachment
  outcomes and review jobs are persisted. Scope/source idempotency prevents a
  repeated discovery from creating another review for unchanged evidence.
- This release uses scheduled discovery, not Gmail Pub/Sub push. The owner-approved
  label is the intake boundary. Configure a Gmail filter or add intended messages
  to that label; the agent does not search unrelated personal mail or claim that
  every message mentioning money anywhere in the inbox has been imported.
- Before its first case review or director conversation for each event after
  startup, the worker reads the current scoped finance snapshot and records a
  `worker_finance_wake` trace. It captures recorded cash/evidence status, current
  obligation/case counts and pending/rejected approvals without any model call,
  approval, payment or ledger mutation. Unknown cash stays unknown. The actor
  independently consults current tools and source documents for its decision.
- This wake receipt describes recorded state, not a complete bank reconciliation
  or proof of complete mail coverage. A receipt retry keeps the same initial
  snapshot payload and idempotency key after uncertain persistence.

## Interactive work and authority

`director_message` is a normal durable command, accepted by the authenticated web
app while the worker is busy. It supports source-backed answers and permitted
record preparation: reported obligations, proposed budget changes and exact
payment approval requests when their prerequisites exist. It has no approval,
signing, transfer, arbitrary shell or outbound email capability. A prompt saying
“approve it” is not an authenticated approval decision.

Migration 022 prioritizes the next lease: expired running work is recovered first;
ready work waiting at least 15 minutes then enters FIFO; recent director prompts
precede ordinary work, case reviews and background learning. This keeps a stream
of new requests from starving background work. Active jobs are not interrupted,
and the daemon still executes one job at a time. A long current learning attempt
can therefore delay a reply; do not promise immediate responses or parallel actor
execution. The UI remains available to accept requests and explicit decisions.

For a live demonstration, finish or defer heavy learning work before the audience
starts using the app. A quiet benchmark window is also required for valid learning
evidence; queue priority is not a substitute for host capacity.

## Judge-driven demonstration

Use the ordinary case conversation or the app's director request entry point:

1. “Review this amended invoice. Who is still owed, what changed, and what can we
   safely do next?” The actor reads the versions and existing obligations.
2. “Prepare a budget adjustment for this revised amount.” A valid result is a
   pending proposed change, never a silently applied budget.
3. Reject the proposal through the authenticated decision control.
4. “The adjustment was denied. What remains outstanding, and what are our options?”
   The response should explain the denial and current position without treating
   the rejected proposal as authority or making a payment.

These are example prompts, not canned outputs or guaranteed model outcomes.
The coordinator's live acceptance must establish the actual source changes,
proposal, rejection and resulting response. The autonomous mail path additionally
needs a real intended message in the authorized label to demonstrate nonempty
mail discovery; a connected empty label alone does not prove it.

## Verification and rollout boundary

Local tests cover immediate scheduler discovery, scope/role/cursor protections,
wake receipt scope and unknown values, receipt retry identity, and wake-before-
actor dispatch. Actual disposable PostgreSQL tests cover interactive priority,
15-minute aging, unexpired lease preservation, expired lease recovery, browser
denial, future work/expired-run exclusion and concurrent lease ownership.

The first SQL test invocation used the older documented port 5432 and failed with
connection refused before any migration ran. The existing isolated test cluster
was found on port 55439; the same tests then passed. No hosted migration, provider
request, worker restart or paid inference was performed by this implementation
subtask. The coordinator applies 022 and verifies the deployed worker separately.
