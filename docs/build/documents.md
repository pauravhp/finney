# Document extraction implementation evidence

October 25, 2026. Scope: `app/documents`, its focused tests and document-intake
documentation. Coordinator owns packaging, Gmail/direct-upload integration,
case aggregation, database migrations and live acceptance.

Implemented bounded real local `pypdf` extraction, UTF-8/CSV parsing, original-byte
private Storage persistence, extraction artifact/source provenance and version
dedup/resumption. Real Claude native PDF/image vision transport is implemented
behind explicit existing model configuration. Jev is not used for OCR. No
mailbox, model or other live private provider call was performed by this builder.

## Verification

Command from application root:
`.venv/bin/pytest tests/test_documents.py tests/test_documents_ocr.py -q`.
The first local pass had 16 passing tests; OCR fixture coverage brought it to
25. The final focused run passed **27 tests in 4.17 seconds**, including explicit
retries, exact parent references and durable OCR provenance/cost dedup.
`.venv/bin/ruff check app/documents tests/test_documents.py tests/test_documents_ocr.py`
is clean (one final import-order fix was automatic).

PDF tests use actual generated, explicitly TEST ONLY PDF documents and the
installed pypdf parser in a separate process: two-page text/page extraction,
password protection, truncated bytes, page/text/size limits, missing text and
deadline termination. Persistence tests use an explicitly named in-memory test
store, not a claimed Supabase execution. OCR tests use explicit provider transport
fixtures to inspect real request construction, page mapping, unknown-field
discard, response/schema/truncation/error handling and provenance. They prove
neither provider availability nor OCR accuracy.

Ruff initially identified import ordering plus a deliberately broad parser-child
exception boundary. Imports were fixed; type errors use TypeError; the isolated
third-party parser boundary has one documented BLE001 exemption so unsafe parser
exception content never reaches operational errors. Focused Ruff then passed.

## Corrections and reusable lessons

- Runtime review found that the local document service could invoke OCR outside
  the run's durable model-call budget. A pure Claude preflight now rejects known
  unsupported/page-limit inputs before reserving. Every eligible request claims
  exactly one call via `reserve_run_inference`; a deterministic UUID binds the
  scoped source version/configuration/policy/hash, and only `claimed is True`
  reaches OCR. Refused/replayed claims preserve originals and local extraction
  with explicit reasons. Claims remain charged after crashes or provider errors.
  Reservation outcomes are stored in the extraction artifact.
- Added actual isolated SQL proof of exhausted-budget refusal with zero provider
  requests and interrupted-source persistence recovery: one durable reservation
  and one mocked provider request remain one after retry; the retry obtains
  `inference_reservation_already_consumed` and persists the unprocessed source.
  Later dedup retries do not request another reservation. This uses actual
  FinanceToolClient/kernel SQL and explicit Storage/provider fixtures. Command:
  `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres .venv/bin/pytest tests/test_documents.py tests/test_documents_ocr.py tests/test_documents_postgres.py tests/test_gmail_documents.py -q`;
  **38 passed in6.46s**, including four actual SQL document tests. Scoped Ruff
  passed. No UI, frozen instructions, model configuration, grants or live
  provider operations changed during this closure.

- Live integration exposed a source idempotency key composed of three 64-character
  digests plus prefixes/version; it exceeded the kernel's 200-character limit.
  The source key is now `document:` plus one SHA-256 of the full identity/version/
  content/policy/extractor tuple (73 characters). New actual isolated PostgreSQL
  integration tests run DocumentService through FinanceToolClient and the real
  kernel SQL, with only object Storage represented by an explicit fixture. They
  verify source/document persistence, original readback, extracted text reads,
  dedup/revisions and that the old oversized key actually raises SQLSTATE22023.
  The earlier in-memory persistence fixture did not enforce the kernel's key
  length and therefore missed this boundary; service tests need an actual SQL
  boundary pass before live acceptance.
- The same SQL test applies migration012 and verifies snapshot metadata exposes
  the original path while preserving the exact eight-field document whitelist;
  extraction policy and other broad internal metadata remain outside it. Command:
  `FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres .venv/bin/pytest tests/test_documents_postgres.py -q`;
  **2 passed in0.71s**, scoped Ruff clean. The initial combined document run was
  **29 passed in4.72s**. No hosted mutation/provider call by this builder.

- Initial raw-byte design added Fernet encryption using the mailbox key. Review
  caught that this would break ordinary authorized Storage inspection and couple
  documents to connector-key rotation. Coordinator directed preserving original
  bytes under existing private Storage RLS; implementation/tests now do so.
- Empty PDF text is not evidence that a document is empty. Missing text remains
  explicit until bounded real native vision runs; it is never replaced by guessed
  receipt text. A digital/scanned mixture retains original page mapping.
- A provider response is not an authorization. OCR pages remain reported,
  uncertain/model-derived and require human verification; arbitrary response
  fields such as `approved` are discarded.
- Immutable raw and extracted artifacts plus source versioning permit recovery
  after an interrupted document-row insertion. Unchanged ingestion does not retry
  provider errors or repeatedly spend OCR tokens; an explicit retry creates a
  reviewable new version.

## Remaining acceptance

Gmail follow-up adds five passing local integration checks in
`tests/test_gmail_documents.py`: actual selected-message PDF extraction and
durability before review/cursor; retry after case-binding interruption;
transient attachment failure without cursor advance; inline originals and
unsupported/oversize visible outcomes; lazy/injectable document factory. HTTP
and database responses are explicit fixtures. The combined focused command
including `test_finance_review.py` had **38 passes, one unrelated payment fixture
failure** after a concurrent payment authorization change; coordinator was
notified. Intake/test Ruff passed. This builder performed no live mailbox
mutation or read.

The coordinator must run actual owned financial document inputs through the
integrated authenticated route/Gmail source, real configured Claude for a scan or
photo, Supabase Storage/Postgres readback and actor review. Local/fixture passes
do not satisfy those live gates. Larger scans, TIFF conversion, advanced layout
recognition and source authenticity remain outside this bounded first version.
