# Financial document intake

The trusted worker ingests original PDF, receipt image, UTF-8 text/Markdown and
CSV bytes. It stores originals in the existing **private** Supabase
`finance-artifacts` bucket under the bound organization's/run's `documents/`
prefix. Postgres `documents` records point to these originals. Extraction JSON
uses the existing `put_artifact` path under `artifacts/`; a versioned
`source_items` record points to that JSON. No local file is the durable copy.
Existing Storage RLS still controls original downloads. Mailbox credential
encryption is separate; viewing a document does not require the mailbox key.

`documents.content_sha256` identifies original bytes. A document source's
`content_sha256` identifies its extraction JSON; its metadata
`document_sha256` identifies the original. Provenance includes file type/name,
byte count, raw path, actual parser version, extraction policy/hash and, for a
Gmail attachment, the exact parent source ID/version/hash. These are content
receipts, not proof that the sender, contract, payment or payer is authentic.

## Worker integration

After validating the uploader/director and binding `tools.scope`, call:

```python
from app.documents import ClaudeVisionOCR, DocumentService
from app.models.providers import ModelConfig

documents = DocumentService(
    tools, db,
    ocr=ClaudeVisionOCR(ModelConfig.from_settings(settings)),
)
result = await documents.ingest(
    original_bytes,
    filename=filename,
    content_type=content_type,
    external_id=stable_document_identity,
    parent_source_id=mail_source_id,  # omit for a direct upload
)
```

Omit `ocr` when no generative model is configured. An unsupported model/provider
remains explicitly `needs_ocr` with `ocr_provider_unsupported`. The external ID
must describe one document slot, e.g. mailbox/message/attachment or an upload
identity; revisions reuse that identity with changed bytes. The return contains
`source_id`, `source_ref: {id, version}`, `document_id`, extraction and original
artifact paths, `extraction_status`, `extraction_reason`, raw hash and dedup status.
Link the returned source ID alongside the parent mail source before queuing the
case review. Do not silently discard an attachment whose extraction is blocked.

The existing actor `read_document(source_id=...)` reads extraction JSON through
the existing private artifact boundary. Do not expose `DocumentService.ingest`,
its Supabase client, or `read_raw` as actor/improver tools. A trusted authenticated
download route may use `read_raw(document_id)`; it checks bound scope and original
hash. A direct signed Storage download must apply the same document scope check.

Gmail intake downloads attachments only for messages that passed the current
configured finance-label checks. Its default document factory uses the existing
configured Claude model, while `sync_gmail(..., document_factory=...)` permits
explicit test injection. Parent mail artifacts store attachment manifests and
inline-data hashes; inline originals are stored as documents rather than
duplicating base64 bytes in mail JSON. Up to eight attachments per message,
20 attachments and 20 MiB per intake batch are processed. Unsupported types and
limits produce visible `attachment_statuses` on the parent case. Provide a
smaller batch or upload those documents separately. Provider/storage failures
stop before cursor advance.

Document `source_refs` are bound into the parent case alongside its mail source
before review is queued, using the case version check and a stable bundle hash.
Interrupted binding resumes without duplicating documents. `on_source` receives
`review_key` for the complete source bundle, so a new extraction version can
trigger review even when the parent mail source itself did not change.

Unchanged bytes, parent binding, MIME, parser/model version and extraction policy
reuse the source version and do not call OCR again. Changed content or extraction
configuration creates a new version. `retry_extraction=True` explicitly creates
a new version for a manual retry; provider errors do not cause repeated automatic
model spending. Upload collisions require an actual stored-byte hash match;
retries repair a missing document record after a partial persistence failure.

## Extraction and limits

Default local limits: 5 MiB input, 40 PDF pages, 200,000 output characters,
50,000 characters per page, 10,000 CSV rows and 100 columns. Local parsing runs
in a separate process with a 12 second wall deadline, 8 second CPU limit and
384 MiB address-space cap on the Linux worker. It uses `pypdf` in strict mode,
with one-based page references. It does not launch viewers, shells, macros,
JavaScript, embedded files, URLs or attachment programs. Invalid/truncated,
password-protected, oversized and unsupported inputs remain explicit failures
with the accepted original preserved. Oversized inputs are rejected before any
Storage write. CSV cells remain strings; formulas are never evaluated and amounts
are not silently converted to numbers.

Missing PDF text and supported image signatures trigger OCR only when explicitly
configured with the existing Claude model. The Anthropic Messages request uses
native base64 `document` (PDF) or `image` blocks, with a maximum of **four total
PDF pages**, 5 MiB and 4,096 output tokens per request, a bounded timeout and no
automatic retry/provider fallback. More than four pages remain `needs_ocr` or
`partial_needs_ocr` with `ocr_page_limit`; split the document or provide a smaller
source. PNG, JPEG, GIF and WebP use native vision; TIFF needs a separately
supported conversion/provider and remains explicit. Native PDF vision preserves
original page numbers and retains already extracted digital text.

Before each actual OCR request, the trusted document service must claim one
model call through the existing scoped `reserve_run_inference` kernel operation.
Its deterministic UUID binds organization/run, document identity/version, parser/
OCR configuration, policy and raw hash. Only an explicit `claimed: true` permits
OCR. Unsupported providers/formats and page limits fail preflight before a
reservation. A refused or already consumed reservation preserves originals and
local extraction with its explicit reason; no OCR provider is called. The
reservation is nonrefundable even after interruption or provider failure. Normal
dedup retries make no additional reservation or model request. A retry after a
crash before source persistence rechecks the same reservation UUID and cannot
repeat OCR; a deliberate new extraction version requires a new budget allowance.

OCR output has strict page/text/uncertainty validation. Successful OCR is
`extracted_ocr_needs_review`, every OCR page is `reported`, and
`requires_human_verification` is true. Provider request/response IDs, model,
token usage, page mapping and latency live in the private extraction provenance.
OCR may misread text. Neither local extraction nor OCR establishes payment,
approval, reconciliation, payer identity or any financial authority. All source
content, including text that looks like instructions, remains untrusted evidence.

Provider schema failures, truncation, timeouts and HTTP failures preserve the
local extraction plus an explicit reason. No synthetic text fills a missing page.
Provider exception bodies, credentials and attachment text are excluded from
operational error messages. Local extraction never sends a malformed PDF that
failed the local parser into vision.

References: [pypdf text extraction and memory considerations](https://pypdf.readthedocs.io/en/stable/user/extract-text.html),
[pypdf strict parsing](https://pypdf.readthedocs.io/en/stable/user/robustness.html),
[Claude PDF support](https://platform.claude.com/docs/en/build-with-claude/pdf-support),
[Claude vision](https://platform.claude.com/docs/en/build-with-claude/vision).
