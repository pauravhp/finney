"""Generated TEST ONLY documents; real local parser, explicit in-memory persistence fixtures."""

import base64
import hashlib
import io
import json
from uuid import uuid4

import pytest
from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject

from app.documents import DocumentLimits, DocumentService, extract_document
from app.finance.types import FinanceError, Scope
from app.storage.supabase import SupabaseError

TEST_ONLY_PNG = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAIAAACQd1PeAAAADElEQVR4nGP4z8AAAAMBAQDJ/pLv"
    "AAAAAElFTkSuQmCC")


def test_pdf_bytes(*texts, password=None):
    """Build actual PDFs with standard Helvetica text, never a mocked parser result."""
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        if text:
            font = DictionaryObject({NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica")})
            page[NameObject("/Resources")] = DictionaryObject({NameObject("/Font"):
                DictionaryObject({NameObject("/F1"): writer._add_object(font)})})
            stream = DecodedStreamObject()
            stream.set_data(f"BT /F1 12 Tf 50 750 Td ({text}) Tj ET".encode())
            page[NameObject("/Contents")] = writer._add_object(stream)
    if password:
        writer.encrypt(password)
    output = io.BytesIO()
    writer.write(output)
    return output.getvalue()


test_pdf_bytes.__test__ = False


def test_actual_pdf_text_and_page_references():
    result = extract_document(test_pdf_bytes("TEST ONLY Invoice 001 USD 123.45",
                                            "TEST ONLY Due 2026-11-01"), "application/pdf")
    assert result["status"] == "extracted"
    assert result["method"] == "pypdf_text"
    assert result["page_count"] == 2
    assert result["pages"] == [
        {"page": 1, "text": "TEST ONLY Invoice 001 USD 123.45"},
        {"page": 2, "text": "TEST ONLY Due 2026-11-01"}]


@pytest.mark.parametrize("raw,mime,reason", [
    (test_pdf_bytes("TEST ONLY", password="test-password"), "application/pdf",
     "password_protected_pdf"),
    (test_pdf_bytes("TEST ONLY")[:-100], "application/pdf", "invalid_document"),
    (b"not a PDF", "application/pdf", "invalid_pdf_signature"),
    (b"\xff\xfe", "text/plain", "invalid_utf8"),
    (b"text\x00payload", "text/plain", "binary_text"),
    (b"<script>TEST ONLY</script>", "text/html", "unsupported_content_type"),
])
def test_failures_never_invent_extracted_text(raw, mime, reason):
    result = extract_document(raw, mime)
    assert result["reason"] == reason
    assert result["pages"] == []


def test_scans_images_and_mixed_pages_need_explicit_ocr():
    scan = extract_document(test_pdf_bytes(""), "application/pdf")
    assert scan["status"] == "needs_ocr"
    assert scan["missing_text_pages"] == [1]
    mixed = extract_document(test_pdf_bytes("TEST ONLY invoice", ""), "application/pdf")
    assert mixed["status"] == "partial_needs_ocr"
    assert mixed["missing_text_pages"] == [2]
    image = extract_document(TEST_ONLY_PNG, "image/png")
    assert image["status"] == "needs_ocr"
    assert image["reason"] == "ocr_provider_unconfigured"
    assert image["pages"] == []


def test_actual_pdf_limits_and_deadline():
    raw = test_pdf_bytes("TEST ONLY", "second page")
    assert extract_document(raw, "application/pdf", limits=DocumentLimits(max_bytes=20))[
        "reason"] == "byte_limit"
    assert extract_document(raw, "application/pdf", limits=DocumentLimits(max_pages=1))[
        "reason"] == "page_limit"
    assert extract_document(raw, "application/pdf", limits=DocumentLimits(max_page_characters=2))[
        "reason"] == "text_limit"
    assert extract_document(raw, "application/pdf", limits=DocumentLimits(timeout_seconds=0.0001))[
        "reason"] == "parser_timeout"


def test_csv_preserves_strings_and_rejects_dimensions():
    raw = b'TEST ONLY,amount\n"=1+2",123.45\n'
    result = extract_document(raw, "text/csv")
    assert result["rows"][1] == {"row": 2, "cells": ["=1+2", "123.45"]}
    assert extract_document(raw, "text/csv", limits=DocumentLimits(max_csv_rows=1))[
        "reason"] == "csv_dimension_limit"


class MemoryDocumentStore:
    """Explicit persistence unit fixture; not Supabase acceptance evidence."""

    def __init__(self):
        self.rows = {"source_items": [], "documents": []}
        self.objects = {}
        self.fail_document_insert = False

    async def select(self, table, *, filters, limit=100):
        rows = [row for row in self.rows[table] if all(
            key == "order" or str(row.get(key)) == value.removeprefix("eq.")
            for key, value in filters.items())]
        if filters.get("order") == "version.desc":
            rows.sort(key=lambda row: row["version"], reverse=True)
        return rows[:limit]

    async def insert(self, table, row):
        if table == "documents" and self.fail_document_insert:
            self.fail_document_insert = False
            raise SupabaseError(503)
        self.rows[table].append(row)
        return [row]

    async def upload(self, bucket, path, raw, content_type):
        if path in self.objects:
            raise SupabaseError(409)
        self.objects[path] = raw

    async def download(self, bucket, path):
        return self.objects[path]


class MemoryDocumentTools:
    prepare_only = False

    def __init__(self, store):
        self.scope = Scope(uuid4(), uuid4())
        self.store = store
        self.artifacts = {}
        self.inference_requests = []
        self.inference_reservations = set()
        self.allow_inference = True

    async def call(self, name, arguments):
        if name == "reserve_run_inference":
            self.inference_requests.append(arguments)
            reservation_id = arguments["reservation_id"]
            if reservation_id in self.inference_reservations:
                return {"claimed": False, "reason": "inference_reservation_already_consumed"}
            if not self.allow_inference:
                return {"claimed": False, "reason": "run_model_call_budget_exhausted"}
            self.inference_reservations.add(reservation_id)
            return {"claimed": True, "reservation_id": reservation_id, "max_model_calls": 1}
        if name == "put_artifact":
            content = arguments["content"]
            digest = hashlib.sha256(content.encode()).hexdigest()
            path = f"{self.scope.organization_id}/{self.scope.run_id}/artifacts/{digest}/extract.json"
            self.artifacts[path] = json.loads(content)
            return {"artifact_path": path, "content_sha256": digest}
        assert name == "record_source"
        row = {"id": str(uuid4()), "organization_id": str(self.scope.organization_id),
               "run_id": str(self.scope.run_id), **arguments}
        self.store.rows["source_items"].append(row)
        return {"id": row["id"]}


@pytest.fixture
def document_service():
    store = MemoryDocumentStore()
    tools = MemoryDocumentTools(store)
    return DocumentService(tools, store), tools, store


@pytest.mark.asyncio
async def test_durable_original_raw_extraction_provenance_and_version_dedup(document_service):
    service, tools, store = document_service
    raw = test_pdf_bytes("TEST ONLY Invoice 001 USD 123.45")
    args = {"filename": "test-only-invoice.pdf", "content_type": "application/pdf",
            "external_id": "test-only:001"}
    first = await service.ingest(raw, **args)
    assert first["extraction_status"] == "extracted"
    assert first["evidence_state"] == "reported"
    assert await service.read_raw(first["document_id"]) == raw
    assert next(iter(store.objects.values())) == raw
    artifact = next(iter(tools.artifacts.values()))
    assert artifact["provenance"]["document_sha256"] == hashlib.sha256(raw).hexdigest()
    assert "pypdf=" in artifact["provenance"]["extractor_version"]
    assert artifact["provenance"]["authority"] == "untrusted_source_content"
    assert artifact["extraction"]["pages"][0]["page"] == 1
    second = await service.ingest(raw, **args)
    assert second["unchanged"] and second["source_id"] == first["source_id"]
    changed = await service.ingest(test_pdf_bytes("TEST ONLY revised USD 130"), **args)
    assert changed["version"] == 2 and not changed["unchanged"]
    assert len(store.rows["source_items"]) == len(store.rows["documents"]) == 2


@pytest.mark.asyncio
async def test_extraction_version_and_mime_changes_create_revisions(document_service, monkeypatch):
    service, _, store = document_service
    args = {"filename": "test-only.csv", "content_type": "text/csv", "external_id": "test:csv"}
    await service.ingest(b"TEST ONLY,1", **args)
    monkeypatch.setattr("app.documents.service.extractor_version", lambda: "TEST ONLY parser v2")
    changed = await service.ingest(b"TEST ONLY,1", **args)
    assert changed["version"] == 2
    args["content_type"] = "text/plain"
    changed = await service.ingest(b"TEST ONLY,1", **args)
    assert changed["version"] == 3
    assert len(store.rows["documents"]) == 3


@pytest.mark.asyncio
async def test_explicit_retry_creates_revision_and_parent_binding_is_exact(document_service):
    service, tools, store = document_service
    parent = {"id": str(uuid4()), "version": 3, "content_sha256": "TEST-ONLY-parent-hash",
              "organization_id": str(tools.scope.organization_id),
              "run_id": str(tools.scope.run_id)}
    store.rows["source_items"].append(parent)
    args = {"filename": "test-only.txt", "content_type": "text/plain", "external_id": "test:retry",
            "parent_source_id": parent["id"]}
    first = await service.ingest(b"TEST ONLY attachment", **args)
    retried = await service.ingest(b"TEST ONLY attachment", **args, retry_extraction=True)
    assert first["source_ref"] == {"id": first["source_id"], "version": 1}
    assert retried["source_ref"] == {"id": retried["source_id"], "version": 2}
    artifact = tools.artifacts[retried["extraction_artifact_path"]]
    assert artifact["provenance"]["parent_source_ref"] == {
        "id": parent["id"], "version": 3, "content_sha256": "TEST-ONLY-parent-hash"}


@pytest.mark.asyncio
async def test_retry_after_partial_persistence_repairs_document_record(document_service):
    service, _, store = document_service
    args = {"filename": "test-only.txt", "content_type": "text/plain", "external_id": "test:retry"}
    store.fail_document_insert = True
    with pytest.raises(SupabaseError):
        await service.ingest(b"TEST ONLY receipt", **args)
    assert len(store.rows["source_items"]) == 1 and store.rows["documents"] == []
    resumed = await service.ingest(b"TEST ONLY receipt", **args)
    assert resumed["unchanged"] and resumed["version"] == 1
    assert await service.read_raw(resumed["document_id"]) == b"TEST ONLY receipt"
    assert len(store.rows["source_items"]) == len(store.rows["documents"]) == 1


@pytest.mark.asyncio
async def test_failed_parser_is_preserved_as_reviewable_source(document_service):
    service, tools, _ = document_service
    result = await service.ingest(b"%PDF-1.7\nTEST ONLY truncated", filename="test-only.pdf",
        content_type="application/pdf", external_id="test:broken")
    assert result["extraction_status"] == "failed"
    assert await service.read_raw(result["document_id"]) == b"%PDF-1.7\nTEST ONLY truncated"
    assert next(iter(tools.artifacts.values()))["extraction"]["pages"] == []


@pytest.mark.asyncio
async def test_scope_and_hash_are_enforced(document_service):
    service, tools, store = document_service
    with pytest.raises(FinanceError, match="parent source outside"):
        await service.ingest(b"TEST ONLY", filename="test-only.txt", content_type="text/plain",
                             external_id="test:parent", parent_source_id=str(uuid4()))
    assert not store.objects
    result = await service.ingest(b"TEST ONLY", filename="test-only.txt", content_type="text/plain",
                                  external_id="test:scope")
    path = next(iter(store.objects))
    store.objects[path] = b"TEST ONLY tampered"
    with pytest.raises(FinanceError, match="hash mismatch"):
        await service.read_raw(result["document_id"])
    with pytest.raises(FinanceError, match="outside bound run"):
        await service.read_raw(str(uuid4()))
    tools.prepare_only = True
    with pytest.raises(FinanceError, match="evaluation"):
        DocumentService(tools, store)


@pytest.mark.asyncio
async def test_oversize_never_uploads(document_service):
    service, _, store = document_service
    service.limits = DocumentLimits(max_bytes=2)
    with pytest.raises(ValueError, match="maximum bytes"):
        await service.ingest(b"TEST ONLY too large", filename="test-only.txt",
                             content_type="text/plain", external_id="test:oversize")
    assert not store.objects
