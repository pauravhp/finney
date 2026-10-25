# Implementation lessons

Only promote lessons supported by observed behavior or inspected source. Keep
product skill learning separate from these engineering process notes.

1. **Hermes import isolation:** source inspection found that `run_agent` loads its
   source-tree `.env`. Use a clean pinned source export and an allowlisted child
   environment before live actor invocation. Runtime owner records verification.
2. **Supabase key generations:** current `sb_secret_*` values are not JWTs. Put
   them in `apikey`; only use `Authorization: Bearer` for an actual user JWT or
   legacy role JWT. Kernel client implements both formats explicitly.
3. **Contract ownership:** freeze scope, money serialization and RPC names before
   parallel UI/runtime work; one builder owns migrations. Money crosses JavaScript
   boundaries as decimal strings, avoiding loss of integer precision.
4. **Composite secret redaction:** connector test found OAuth state still exposed
   through the authorization URL's dataclass repr after the state field itself
   was hidden. Exclude both from repr; regression test protects this boundary.
5. **Authentication failure is a hard stop:** coordinator repeated hosted database
   probes while interpreting a URI and triggered a temporary IP ban. See
   INCIDENT-001-database-auth.md. Validate syntax offline; require corrected
   credentials and one explicit TLS connection check. Never guess/normalize/retry
   credentials against a live database or work around its ban.

6. **Supabase membership identity evaluation:** the dashboard flagged the initial
   `own_membership_read` policy for evaluating `auth.uid()` per row. Migration
   006 uses `(select auth.uid())`, preserving the user filter. A hosted read-only
   check verified the migration checksum and actual policy definition. Verify
   that identity changes on a reused connection still select only that member.
7. **Inspect existing runtime integrations before prescribing duplicate setup:**
   pinned Hermes includes Google Workspace and Himalaya skills. Workspace still
   needs Google OAuth credentials/consent; Himalaya supports email via an app
   password where available. Neither supplies Supabase Google SSO. Inspection
   found no existing mail credentials at the standard Hermes/CLI locations on
   this build host; no personal Hermes configuration was changed. Upstream skill
   availability does not mean its output is already wired into our scoped intake.


8. **Custom mailbox homes matter:** standard Hermes credential checks missed the
   working previously authorized readonly grant. Inspect actual runtime wiring before
   requesting a new OAuth client. Explicit authorized reuse should copy encrypted
   credentials, verify mailbox identity in isolation, and leave source files intact.
9. **Auth failure plus a scheduler:** a permanently failed job alone does not stop
   a scheduler from creating another one. Block the unchanged connection on permanent
   provider failure, using CAS to protect a concurrent reconnect.
10. **Approval policy changes are authority changes:** bind policy version/count
    into immutable action hashes, invalidate pending proposals, recheck current
    authority at reserve/send, and keep past idempotency results from authorizing a
    new send. Role/quorum rules apply in both solo and two-person modes.
11. **Live snapshot checks must respect redaction:** the browser intentionally sees
    provider/status, not connection credential metadata. Verify backend identity
    from separate protected evidence; do not expose it merely to satisfy a test.
