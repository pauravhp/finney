# Stored procedure comparison

Benchmark-created procedure versions can lack `metadata.generation.output.procedure`.
The Learning screen previously downloaded only the selected artifact and could
not show a baseline/candidate diff from those versions.

The existing Procedure renderer is now a small separate component with the same
classes, patch display, two-column comparison and raw artifact inspection. Its
on-demand **Compare stored procedures** action reads the selected version and
its recorded parent through the actual browser Supabase Storage client and
current user's session. It makes no automatic artifact request on render.

Both version paths must belong to the current organization/run's `artifacts/`
namespace; explicit row scopes, parent identity and skill lineage are checked
before any download. Traversing and encoded traversal paths are rejected. The
existing 1 MiB inline limit remains. SHA-256 is calculated on each downloaded
artifact's original bytes and must equal that version row's `content_sha256`.
Neither generation metadata nor an artifact's own claims can override the digest.
Source text is rendered as escaped React text, never HTML.

When both files contain a single bounded Investigation procedure section and
their protected prefix/suffix match, those sections are compared. Otherwise both
complete artifacts are compared, preserving visibility of authority changes and avoiding
a mixture of full files, sections and metadata. Raw candidate inspection remains
available. Loading, access denial, oversized files, invalid hashes and checksum
mismatch produce contained errors with retry through the same action. Untrusted
Storage error bodies are not displayed. Scope/version changes invalidate pending
results so a previous run's loaded text cannot appear in the new selection.

Recorded generation text remains a clearly labeled fallback. It does not become
a verified stored comparison when either artifact fails. If no parent row is
available, the component offers candidate-only inspection and states why no
baseline comparison can be shown. A NULL parent link is stated explicitly; the
UI does not invent a parent, repair lineage or claim learned improvement.

## Verification

- **53 web unit tests passed**, including original-byte hashing before CRLF
  normalization, foreign/traversing/incorrect parents, access and size failures,
  missing hashes, consistent representation and metadata/unlinked-parent fallback.
- TypeScript and the production Next.js build passed.
- **10 browser tests passed**: desktop/mobile artifact-only comparison, denied
  baseline plus recovery, foreign baseline rejected before Storage reads, missing
  parent candidate-only inspection and tampered-content rejection.
- Browser fixtures use the real React component and real Supabase Auth/Storage
  SDK with an explicitly fake session and intercepted provider responses. The
  actual Storage request carries the fake user's bearer token. These checks do
  not establish hosted Auth/RLS policy behavior or read a real private document.
- Desktop/mobile screenshots were inspected together. Existing layout and
  wrapping remain; neither viewport has horizontal overflow. Impeccable's narrow
  harden guidance and craft floor were applied; its detector returned `[]` for
  the changed UI targets. No branding or visual-world change was made.

Hosted acceptance is recorded separately from these scripted browser checks.
The UI makes no database edits, model calls or promotion decisions.
