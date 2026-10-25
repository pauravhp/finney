# Finance kernel build evidence

Status: kernel implementation ready for coordinator integration; no hosted
Supabase verification claimed. Migration frozen after the verification below.

Final migration SHA-256:
`768fea52efb024f2b0c57c3fd4b03bff98b0bedcdba514b2ca8f484e3be02200`.

Additional explicit opening snapshot migration:
`202610250003_opening_snapshot.sql`, SHA-256
`1b8348acc7f07cda4e9947d4862dc44f521c7c242e35b71a445a068124aa6f73`.

## Integration contract

Python imports: `app.storage.supabase.SupabaseClient`,
`app.finance.tools.FinanceToolClient`, `app.finance.jobs.JobQueue`,
`app.finance.types.Scope`. HTTP dependency: `httpx>=0.27,<1`.

Browser RPCs use authenticated Supabase JWT identity, never a caller supplied role:

* `get_finance_snapshot(p_organization_id uuid,p_run_id uuid) -> jsonb`
* `enqueue_finance_command(p_organization_id uuid,p_run_id uuid,p_command_type text,p_payload jsonb,p_idempotency_key text) -> uuid`
* `approve_finance_proposal(p_proposal_id uuid,p_expected_action_hash text,p_decision text) -> jsonb`; decision is `approve` or `reject`.

Snapshot v1 (amounts are decimal strings or null):

```json
{
  "organization": {"id":"uuid","name":"string"},
  "run": {"id":"uuid","name":"string","status":"active","currency":"USD","revision":0},
  "position": {"currency":"USD","cash_minor":null,"committed_minor":"0","receivable_minor":"0","available_minor":null,"evidence_status":"unknown","reconciled_at":null},
  "cases": [{"id":"uuid","title":"string","status":"open","version":1,"data":{},"updated_at":"timestamp"}],
  "approvals": [{"id":"uuid","action_hash":"hex","action":{},"status":"pending","required_approvals":2,"approval_count":0,"decisions":[],"expires_at":"timestamp","created_at":"timestamp"}],
  "activity": [{"id":1,"event_type":"string","payload":{},"created_at":"timestamp"}],
  "improvements": {"skill_versions":[],"eval_runs":[],"eval_results":[],"promotions":[]},
  "connections": [],
  "worker": {"status":"unknown","last_seen_at":null},
  "updated_at":"timestamp"
}
```

`memberships` columns: organization_id,user_id,role,active. Roles:
director,finance,approver,viewer. `demo_runs` columns: id,organization_id,name,
status,currency,revision,owner_user_id,is_demo,expires_at,cash_established,
cash_evidence_status,reconciled_at,created_at,updated_at. Non-demo runs readable by
active organization members; demo runs require their owner, including within one
organization. All scoped child reads use the same rule. Never select a run from
another visitor by accepting its UUID alone.

Realtime topic `finance:<organization_id>:<run_id>`, private channel; event
`state_changed` contains only run scope and an audit cursor, never raw traces.
Private Realtime requires disabling public channels in hosted project settings.

Finance tool calls are server-scoped. Arguments cannot override organization/run.
Prepare-only mode permits reads, arithmetic and trace/evaluation evidence writes;
it rejects operating financial mutations and execution. Proposal hash is computed
by PostgreSQL from its canonical JSON representation; use returned hash unchanged.

## Evidence log

- Initial inspection: no PostgreSQL executable installed. Downloading packages to
  `/tmp/director-finance-pg` for an isolated local integration cluster; no existing
  services or system package installation will be changed.
- Reviewed current official Supabase Realtime authorization docs. Do not alter
  RLS ownership on `realtime.messages`; create only a scoped receive policy.
  Sources: <https://supabase.com/docs/guides/realtime/authorization> and
  <https://supabase.com/docs/guides/realtime/subscribing-to-database-changes>.

- 2026-10-25: Downloaded PostgreSQL 17 Debian packages to a task-specific /tmp
  directory, extracted without package installation and started a loopback-only
  cluster on port 55439. Platform schemas/auth/realtime functions in
  `tests/finance_postgres_bootstrap.sql` are explicitly test-only fixtures.
  No unrelated service was changed.
- First test command: `FINANCE_TEST_DB_URL=... .venv/bin/pytest -q
  tests/test_finance_domain.py tests/test_storage_http.py tests/test_finance_postgres.py`.
  Result: 17 passed, 2 failed. Root cause: a PL/pgSQL variable named `currency`
  collided with the ledger column in reservation SQL. Renamed the variable to
  `v_currency`. Same command retest: **19 passed**. This is local integration,
  not hosted Supabase execution.
- Verified actual local PostgreSQL behavior for authenticated RLS and forbidden
  browser writes; exact action hashes; proposer exclusion and distinct approvals;
  source-change invalidation; idempotency collisions; deferred balanced journal
  validation; per-owner demo resets; competing lease acquisition and stale-token
  rejection; and receipt matching with atomic ledger/obligation settlement.
- Reusable lesson: parsing a migration does not execute deferred SQL branches.
  Exercise complete reserve/submit/confirm transactions on PostgreSQL before
  claiming the payment kernel works.

## Additional integration details

`SupabaseClient` sends new `sb_secret_`/`sb_publishable_` keys only as `apikey`;
an explicit user JWT is sent as Bearer. Legacy JWT keys also use Bearer. The
client does not retry writes after uncertain network failures. Trusted connector
code can call `insert(table,values,upsert=False,on_conflict=None)` and
`update(table,values,filters=...)`; those methods must not be actor tools.

`connector_secrets`: organization_id/run_id/provider primary key,
encrypted_token text,updated_at. `oauth_pending`: state_hash primary key,
organization_id/run_id/provider/user_id,encrypted_verifier,redirect_uri,
expires_at,created_at. Both have RLS and no authenticated browser grants.

Worker queue: `JobQueue(client,worker_id).lease(lease_seconds=120)`,
`renew(job_id,lease_token,lease_seconds=120)`, `ack(job_id,lease_token,result)`,
`fail(job_id,lease_token,error_code=...,retryable=False)`, `heartbeat()`.
Expired leases cannot ack/fail/renew, and run reset revokes its leases.

`FinanceToolClient(scope,client).call(name,args)` is async. Reads:
get_finance_snapshot/get_financial_position/get_case/get_trace/list_due_work/
get_obligations/get_active_skill/get_approval_status/get_payment_status,
read_document,read_artifact. Deterministic operations: calculate_cash_forecast,
simulate_commitment,validate_prepared_decision. Writes require idempotency_key;
record_source,record_case,record_finding,propose_obligation_update,post_ledger,
create_approval_request,reserve_approved_payment,transition_payment,confirm_payment,
record_trace,save_skill_version,record_eval_run,record_eval_result,
record_promotion,set_active_skill_version,initialize_skill_baseline,
rollback_skill_version,set_connection_status,record_report. Actor-facing runtime
must expose only its explicit tool allowlist; bootstrap, evaluation and payment
executor methods belong to their trusted services.

`for_evaluation(snapshot)` returns a prepare-only scope-bound client whose
financial reads use a deep copy of captured data. Missing captured evidence
fails; no live-state fallback. Trace/evaluation writes remain available for
measurement. Live finance changes, skill activation and payments are denied.
Captured documents need content included explicitly by the trusted evaluator;
the browser snapshot includes only source IDs/versions/hash/path.

Private artifact tools: put_artifact({name,content,content_type,idempotency_key})
returns artifact_path/content_sha256; read_artifact requires the bound run prefix.
Content is durably uploaded to finance-artifacts; duplicate objects are accepted
only after downloaded bytes match their SHA-256. Browser Storage reads use user
JWT and run-scoped RLS.

Snapshot extensions: source_items[] (IDs/versions/hash/path), obligations[]
(decimal-string amounts), reports[] (id/cutoff/data/artifact_path/created_at),
improvements.trace_events[] (actor_completed IDs plus projected diagnosis fields).

Baseline initialization requires a saved parentless version with status baseline
and no existing active version. Promotion uses candidate evaluation rows,
details.group=regression, hard-invariant outcomes, metrics.gate_passed and active
version compare-and-swap. Rollback requires the scoped promotion's original
current/previous relationship plus reason; it changes future sessions only.

## Remaining provider gates

Hosted migrations, Auth identity verification, actual private Realtime delivery
and actual private Storage upload are not established by local database/HTTP
transport tests. Exact external Coinbase receipt verification belongs to the
payment adapter; accepting a typed receipt in this kernel is not a provider
verification claim. The executor must inspect durable payment state before
external submission and investigate submitting/uncertain attempts without
blindly retrying a wallet operation.

## Final verification and limits (2026-10-25)

After implementing lease renewal, connector cursor persistence, source dependency
propagation, baseline/promotion/rollback and receipt completeness, the final
command was:

```sh
FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres .venv/bin/pytest -q tests/test_finance_domain.py tests/test_storage_http.py tests/test_finance_postgres.py
.venv/bin/ruff check app/finance app/storage tests/test_finance_domain.py tests/test_finance_postgres.py tests/test_storage_http.py --output-format concise
```

Result: **24 passed in 0.59s; all lint checks passed**. Twelve tests exercise a
real temporary PostgreSQL database. The remaining tests use deterministic domain
inputs and explicitly test-only HTTP transport doubles. They do not imply any
live model, Gmail, Coinbase, hosted Supabase, or hosted web acceptance.

Further reviewed edge cases and fixes:

- SQL three-valued logic can let missing JSON keys skip a rejection predicate.
  Approval hashes now use `is distinct from`; command/action/receipt completeness
  and status are checked explicitly. Null hash and missing receipt status are
  rejected in PostgreSQL tests.
- Approvals are rechecked immediately before marking a reserved payment
  submitting. Changed evidence or revoked memberships cannot use a previously
  reserved action as a stale execution permission.
- Two concurrent 600-unit reservations against 1000 units of cash produce one
  payment, not 1200 units of reservations. This is a real competing-connection
  test using the run row lock.
- All action/report JSON keys ending in `_minor` or `_base_units` are normalized
  recursively to decimal strings before storage. A value above JavaScript's safe
  integer limit is tested. Hashes are computed after normalization.
- Source revisions reopen only their dependent cases, retaining old immutable
  sources. Financial proposals are conservatively invalidated run-wide; narrower
  proposal invalidation is a future refinement, not a claimed optimization.
- Connector state persists supplied nonsecret metadata/cursors using a merge.
  A regression test ensures a new Gmail history ID retains mailbox metadata.
- Read artifacts are checked against a content-addressed SHA in their path when
  present. Source semantic hashes and serialized artifact byte hashes are distinct.

Not yet provided by this kernel: hosted access proof; wallet signer/provider
receipt verification; a verified-recipient onboarding flow; browser budget
allocation editing; production rate/cost limits for a public visitor deployment.
Budget/fund schema exists, with commitment simulation and obligation/cash/report
queries, but there is no separate approved budget-change execution RPC yet.
The browser may not write budget rows directly.

Owner-isolated demo runs deliberately permit only their owner. A real second
human payment demonstration must use a non-demo organization run with explicit
memberships. Inviting another human into one owner's temporary demo run is not
implemented; it must not be represented as working.

The local cluster at `/tmp/director-finance-pg` remains available to the coordinator
for independent checks. All test databases were randomly named and dropped after
their test module. Stop with the extracted task-specific pg_ctl when finished;
this cluster is never an application persistence default.

### Atomic promotion review fix

Before hosted apply, runtime review identified a failure window: updating the
active skill then recording its promotion in a second RPC could leave no rollback
link if the second request failed. Fixed `set_active_skill_version` to atomically
insert its promoted row and return promotion_id with the new/previous IDs. Runtime
uses this result instead of a second promotion write. Rollback already updates the
active version and records rolled_back in one transaction. PostgreSQL regression
asserts the promoted row exists when activation returns and an idempotent replay
produces the same ID and exactly one promotion. Full kernel retest: **24 passed
in 0.64s**. Lesson: persist the authorization/version pointer and the evidence
needed to reverse that pointer in the same database transaction.

### First-use cash initialization fix

Packaging review found CSV opening_balance was only evidence intake, leaving
cash unknown without a trusted initialization command. Added a separate service
RPC `establish_finance_opening_cash(p_organization_id,p_run_id,p_actor_id,
p_amount_minor,p_currency,p_as_of,p_evidence_source_id,p_idempotency_key)`.
The coordinator passes actual queued-job identity, never a payload actor. It must
be an active director; a temporary demo also requires its owner. The immutable
source must have source_type owner_attestation and metadata evidence_status
owner_attested, attested_by actual director, exact amount_minor/currency/as_of
(timestamp comparison is semantic). Missing/future/negative snapshots fail.

Cash zero is a real attestation: it establishes known zero without inventing
zero-value journal postings. Positive cash creates one balanced cash/opening_equity
journal. The run retains owner_attested status, not provider confirmation.
Idempotent exact replay returns the same result; conflicting key or a second
opening requires reviewed reconciliation. Three local PostgreSQL tests cover
zero/nonzero, duplicates/conflicts, exact source identity/amount and browser denial.
The first two applied migrations were left unchanged.

Agent-generated proposals should bind proposer identity to the agent (no human
UUID) while preserving the initiating director in trace evidence. This permits
the director and one distinct human approver to satisfy two humans. Manual human
proposals retain the existing proposer self-approval rejection. The database
continues to derive every actual human approval from verified auth.uid().

### Independent integration review and final corrective migrations

Reviewed coordinator intake/OAuth/dispatch with no hosted/provider/model calls.
Reported these concrete issues before coordinator-owned files were changed:

- A source committed before case creation could be treated as unchanged on retry,
  permanently skipping its missing case. Coordinator now repairs/reuses the case
  and returns its identity. Crash/retry regression passes without duplicate source.
- Inbox cursor was committed before durable review enqueue. Coordinator moved
  enqueue into an on_source callback before checkpointing. Tests inject enqueue
  failure and verify no cursor update; successful order is evidence -> review job
  -> connection CAS checkpoint -> sync summary. Checkpoint compares updated_at so
  a stale scan cannot overwrite reconnect state.
- OAuth reconnect retained prior mailbox cursor/label metadata. Coordinator now
  clears it, namespaces provider IDs with mailbox identity and rechecks current
  director authority. Callback regression verifies the new mailbox starts fresh.
- Expiring OAuth state at each request's own time allowed two overlapping callbacks
  processed in reverse timestamp order to consume it. Coordinator now expires at
  a fixed past timestamp. A deliberately reversed callback test allows exactly one
  success and one400, with only one token-save path.
- Actor proposal schemas lacked exact transfer contract/decimals/base units/sender.
  The regression initially failed at TransferIntent validation. Coordinator now
  derives those fields using trusted settings before hashing; the same test passes
  and the agent remains the proposer rather than a fabricated human approver.

**Storage correction:** the original policy's unqualified `name` resolved to the
inner demo_runs.name, denying ordinary authorized artifact reads. A real local
PostgreSQL test first returned no authorized objects. Migration004 qualifies
storage.objects.name. Positive owner read now passes; other organization/visitor
objects and private helper tables/functions remain denied. First post-fix run
also exposed a misplaced test-body tail (NameError); restored the original opening
test body and both Storage/opening regressions passed. Lesson: test successful
authorized reads as well as permission denials; deny-all can pass negative tests.

`202610250004_storage_read_scope.sql` SHA-256:
`1a40d03e3637be03086809956a080db5f257ed74f48315054371930b9afc27d9`.

**Prepared review persistence:** new helper
`app.finance.review_persistence.persist_actor_review(tools,before_case,outcome,job)`
captures actual output, citations, completed trace and skill provenance. It advances
the expected case version only for successful same-case record_finding events
whose expected versions form the recorded chain. An external version/source change
blocks persistence; it is not rebased onto new evidence. Unsupported citations or
claims of executed/approved settlement are rejected. Stored findings are explicitly
unverified prepared recommendations with effects_completed=false.

Dedicated service-only RPC record_finance_case_review atomically validates the
scoped review job/actual actor_completed output, compares case version/source IDs,
updates only the finding/status, preserves closed cases and existing evidence,
and appends trace/audit. It increments case version but leaves the financial run
revision unchanged, so a pure annotation does not stale a newly prepared proposal.
Tests prove two actual authenticated approvals and payment reservation still work
after annotation; forged output and revised source context are rejected. Actor
tool allowlists do not include this trusted persistence method.

`202610250005_prepared_case_reviews.sql` SHA-256:
`c70211f7774e3183fa41e00dbad1c3975d2fee09f27a7dc743e478340a270f7a`.
Migrations001-003 remain unchanged. No coordinator service/runtime file was edited
by this builder during the review.
