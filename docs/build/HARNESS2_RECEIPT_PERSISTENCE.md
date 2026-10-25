# Harness2 search receipt persistence repair

The October 25 online attempt completed its real search and uploaded both its
archive part and manifest. The next operation, recording the search receipt,
failed before candidate persistence or evaluation began. The attempt's original
failed job and provider evidence remain unchanged.

The receipt called the finance kernel's `record_trace` operation without its
required idempotency key. The kernel rejects that with SQLSTATE 22023. Earlier
in-memory search fixtures accepted the malformed call, so they missed this
integration failure. This was a coordinator persistence defect, not evidence
that the learned candidate failed financial evaluation.

The receipt now uses a deterministic key binding the source trace identity and
exact archive content hash. A new test runs actual pinned upstream Harness2 with
scripted editor/probe outputs and fixture Storage, then writes the receipt through
real isolated PostgreSQL. It reproduces the missing-key rejection, verifies the
fixed path, and verifies that replay stores exactly one receipt without promotion.
Ten existing Harness2 fixture tests and this PostgreSQL test passed. These checks
use no paid provider calls and establish no financial learning gain.

The repair does not replay search, reset an attempt, refund reservations, consume
holdouts or activate a candidate. Any separately authorized continuation must
verify the archived candidate and original frozen evaluation/model/context,
retain the original inference ceiling, and use the unchanged native gates.
