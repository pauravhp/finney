# OpenCode step hint and private provider failures

The pinned OpenCode runtime appends an assistant `MAX_STEPS_PROMPT` when
`step >= agent.steps` (`session/prompt.ts`, lines 1178 and 1281 at the inspected
pin). With a one-call editor and `steps=1`, this changes its first provider
request into an assistant-prefilled conversation. The configured Claude model
rejects that request because it requires the conversation to end with a user.

The adapter sets the runtime's hint to **reserved call limit + 1**. The external
FinanceBridge remains the hard inference limit, including the editor's single
forwarded request. Thus the hint's assistant prefill cannot enter an authorized
provider request; a further attempt hits the existing allowance guard first.
No runtime/model fallback or extra paid format-repair call is introduced.

Non-200 provider responses now retain an error prefix only in the parent bridge's
private diagnostic. Reads stop after the bounded prefix; stored UTF-8 body size
is at most 65,536 bytes after redaction, including replacement-character or secret
marker expansion. Known provider/local credentials, including a partial key cut
at the capture boundary, are redacted. HTTP status and truncation/read status
accompany the private body. Public exceptions, bridge response bodies and ordinary
provider-call receipts retain only their existing safe typed status/code fields.
The first provider error still latches the invocation and cannot be retried.

Regression checks use the actual pinned OpenCode server with a scripted provider
that returns HTTP 400 whenever the payload ends in an assistant message. The
one-call editor completes with `StructuredOutput` as its sole tool, one forwarded
call and a final user message. Separate checks exercise finite error-stream
consumption, 64 KiB bounds, invalid UTF-8, credential truncation/redaction and
private-only failure attachment. No model call or canonical checkout edit is
performed by these tests.
