# Actionable finance rejections without provider-data disclosure

The changed-document demonstration exposed an observability gap: an actor tried
to update an obligation with both an old source version and its replacement.
The existing database correctly refused the superseded reference, but the actor
and later diagnosis saw only `finance_tool_error` / `SupabaseError`. That hid the
distinction between a financial input rejection and an infrastructure outage.

The Supabase adapter now recognizes three exact application-owned SQLSTATE/message
pairs from HTTP 400 responses to `finance_kernel_call`. They become fixed tokens:
`source_reference_not_current`, `source_references_required`, and
`source_references_invalid`. The first deliberately covers missing, superseded or
out-of-scope evidence because the database does not distinguish those causes in
its response. It does not pretend every such rejection proves a stale document.

Both OpenCode and Hermes use the same bounded error projection. A recognized
rejection tells the actor to consult current in-scope documents, preserve earlier
documents as history, and avoid repeating unchanged references or claiming the
write succeeded. Unknown SQL/provider responses and authentication failures remain
generic. Raw messages, details, hints, credentials and request bodies are not
retained in the exception or exported by this projection. Matching requires the
exact SQLSTATE, exact message, expected endpoint and status; a matching prefix
with appended private text is insufficient.

No database guard, approval rule, evaluator answer or promotion gate changed.
The prior failed attempt remains unchanged. This is an engineering correction
to observable tool feedback, not a measured learned improvement.

Verification: 49 targeted storage/error/actor-format tests and Ruff passed.
Explicit HTTP and process fixtures checked both runtime boundaries, identical
actor/trace feedback, no tool replay, unknown/auth failures and secret-bearing
response details. These checks used no hosted calls or model inference.
