# Finney OpenCode actor

The optional actor uses the actual OpenCode **1.19.4** headless server, not a
direct-model substitute. The model stays the caller's `ModelConfig`, including
Claude Sonnet 4.6 and the initial 1,600 output-token cap for comparison with the
Hermes baseline. Changing the actor does not replace the finance kernel, source
contracts, approval gates, evaluation gates, mailbox connector or persistence.

## Install the app-owned pin

From the application root, in its existing Python environment:

```bash
python -m app.runtime.opencode_setup
```

This explicit command downloads the official `opencode-linux-x64-baseline.tar.gz`
release into a temporary installation directory, verifies its pinned SHA256,
extracts only the regular `opencode` member, verifies the executable SHA256, and
atomically installs `.runtime/opencode/opencode`. It never uses a global OpenCode
installation or changes shell startup files. An existing executable must match
the pin. No installation happens during a finance job.

This first pin supports Linux x86_64. Other platforms fail explicitly until their
release assets and executable hashes are added and tested. `FINANCE_OPENCODE_BINARY`
can select another app-owned copy of the same exact executable; symlinks and hash
drift fail before execution. Do not commit `.runtime/` binaries.

Pin receipt: `app/runtime/opencode-lock.json`, source revision
`148842ef7cb1bc34192b3fff57d0f9721ab9c801`, official release October 22, 2026.
The archive digest is also published in GitHub's release-asset metadata.

## Adapter contract

```python
from app.runtime.opencode import OpenCodeActor

actor = OpenCodeActor(model_config, max_iterations=8, timeout_seconds=120)
result = await actor.run(
    prompt, skill, scoped_finance_tools,
    allowed_tools=allowed_tools,
    policy=immutable_policy,
    max_model_calls=reserved_call_allowance,
)
```

`run` preserves `HermesActor.run`'s arguments and result keys: `output`,
`tool_events`, and `evidence`. Finance decisions use OpenCode's native server
`format: {type: json_schema, schema: ..., retryCount: 0}` and `StructuredOutput`.
The existing deterministic `validate_decision_shape` still runs after capture.
Optional `finance_report` data allows corpus reporting tasks without exposing
evaluator answers. Director messages remain human-readable text with consulted
source receipts. Onboarding has only its three existing setup tools and its own
structured envelope.

The coordinator owns actor selection/settings integration. This adapter can be
instantiated directly without changing the default Hermes actor. It never falls
back to another runtime, model or direct completion path on failure.

## Capabilities and isolation

Each invocation creates a new private temporary HOME, XDG config/data/cache/state
and empty working directory. OpenCode project configuration, personal Claude
instructions/skills, external skills, default plugins, model-catalog fetch,
updates, automatic compaction, sharing and file watching are disabled. Built-in
build/plan/explore/general/title/summary/compaction agents are disabled. The
temporary session database and process group are removed on completion, failure,
timeout or cancellation. No personal runtime config or credentials are inherited.

Permissions deny `*`. The exact allowed finance MCP tools are the only effectful
exceptions. Their OpenCode names have a `finance_` prefix; application events and
the tool service retain the original names such as `get_case`. `StructuredOutput`
is the sole non-finance exception for capturing a structured answer; it grants no
file, network, payment or approval capability. Director replies cannot call
`record_finding`, matching the baseline. The service's allowlist and scope remain
authoritative even if a model requests another tool.

The MCP bridge binds an ephemeral loopback port and requires a random bearer
token. OpenCode's own REST server uses a separate random Basic Auth credential.
The real provider key stays exclusively in the parent Python bridge. The child
receives only the disposable loopback token; the temporary config contains no
real provider, mailbox, wallet, Supabase, signer or personal-profile secrets.

This is model capability isolation around trusted pinned runtime code, not a host
OS security sandbox. All durable application records still belong in Supabase;
OpenCode's temporary local SQLite database is disposable runtime state only.

## Bounds, receipts and failures

The loopback provider proxy enforces the configured model, maximum output tokens,
advertised tool set and actual forwarded request allowance. Every attempted
upstream inference is counted before forwarding, including any SDK/runtime retry.
The first provider error latches the invocation, so retries cannot re-contact the
provider. The actor additionally sets OpenCode's step limit and a whole-invocation
timeout. The proxy caps response/request bodies and finance-tool calls.

Provider responses are checked before forwarding. A hallucinated unpermitted
tool becomes an explicit blocked event and failed invocation; incomplete streams,
truncation, auth/transport failure and invalid structured output cannot become a
successful decision. The adapter does not invent missing output or spend an
extra format-repair call.

Success evidence includes runtime/version/revision/model/output contract, actual
`api_calls`, numeric provider usage, provider request IDs, per-request status,
finish reason/token cap/tool names and elapsed time. No monetary cost is inferred
from OpenCode's custom-provider catalog entry.

`OpenCodeActorError` subclasses `HermesActorError`, preserving the existing trusted
private-diagnostic persistence path. Its public message is only a safe error code.
Private diagnostics retain the original final text/JSON string (including native
StructuredOutput arguments before schema rejection), bounded tool events,
completion status, request receipts and consumed allowance. No reasoning or full
message history is exported. Known provider and local transport secrets are
redacted even if echoed by untrusted output. Persist diagnostics only to private
Storage, just as for Hermes failures.

## Verification record — October 25, 2026

The release archive and executable SHA256 checks passed. The actual pinned
server executed against explicitly scripted upstream HTTP responses, exercising
the real OpenCode REST server, native AI SDK, MCP connection, scoped Python tools
and native structured output. This is runtime integration evidence, not a live
Claude run, finance-quality measurement or learned improvement.

Final focused result: **22 passed in 38.90s**; Ruff checks passed for all three
new Python runtime modules and the focused test file. The installer also
verified the existing app-owned executable without another download.

Run the focused checks:

```bash
python -m pytest tests/test_opencode.py -q
ruff check app/runtime/opencode.py app/runtime/opencode_bridge.py app/runtime/opencode_setup.py tests/test_opencode.py
```

Covered cases: finance MCP plus structured decision; director text and provenance;
genuine prepare-only `FinanceToolClient` obligation/due-work array results;
onboarding; report extension; hard call-budget exhaustion; upstream auth failure
with no retry; invalid schema/plain-text final; truncation; blocked built-in tool;
incomplete provider stream; tool exceptions; credential-echo redaction; denied
permissions; clean environment; pin drift; invalid allowance; timeout cleanup.
Actual-runtime tests skip when the pin is not explicitly installed; bridge unit
tests still run. No paid inference, real mailbox access, payment, deployment or
personal runtime modification was performed by these checks.

Design lessons: OpenCode's step setting alone is not a hard financial inference
allowance, so the external proxy counts actual HTTP forwards. The default title
agent can spend an otherwise hidden model request, so it is disabled and the
session gets a fixed title. Native structured output is itself a tool, so an
explicit `StructuredOutput` permission is needed under deny-all permissions.
The real runtime fixture also accepted an empty blocker `supporting_refs` array
despite `minItems: 1` in the supplied schema. The independent existing decision
validator rejected it as `invalid_finance_decision_schema` and retained the
original JSON privately. Native structured output does not replace that gate.
Review also caught a dict-only bridge assumption: real obligation and due-work
reads return arrays. The bridge now preserves JSON-native results, and the actual
runtime regression uses the genuine prepare-only client with forbidden-network
snapshots to verify those arrays reach the model and trace unchanged.

## Primary references

- [Official server API](https://opencode.ai/docs/server/) and the pinned server's
  `/doc` OpenAPI endpoint.
- [Official MCP configuration](https://opencode.ai/docs/mcp-servers/).
- [Official permission rules](https://opencode.ai/docs/permissions/).
- [Pinned source](https://github.com/anomalyco/opencode/tree/148842ef7cb1bc34192b3fff57d0f9721ab9c801):
  inspected paths are listed in the lock receipt.
- [Pinned official release](https://github.com/anomalyco/opencode/releases/tag/v1.19.4).
