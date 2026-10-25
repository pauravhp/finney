"""Explicit provider transport fixtures. These tests do not call Claude or prove OCR accuracy."""

import base64
import json
from dataclasses import replace

import pytest
from test_documents import TEST_ONLY_PNG, test_pdf_bytes

from app.documents import ClaudeVisionOCR, DocumentLimits, OCRLimits, extract_document
from app.models.providers import ModelConfig, ModelError


@pytest.fixture
def model():
    return ModelConfig("claude-TEST-ONLY", "https://api.anthropic.com/v1", "TEST-ONLY-KEY",
                       api_mode="anthropic_messages")


def response(pages, *, stop_reason="end_turn"):
    return {"id": "TEST-ONLY-response", "model": "claude-TEST-ONLY", "stop_reason": stop_reason,
            "content": [{"type": "text", "text": json.dumps({"pages": pages})}],
            "usage": {"input_tokens": 100, "output_tokens": 20}}, "TEST-ONLY-request"


@pytest.mark.asyncio
async def test_real_image_request_protocol_and_reported_unverified_result(model, monkeypatch):
    calls = []

    def post(url, headers, payload, timeout):
        calls.append((url, headers, payload, timeout))
        return response([{"page": 1, "text": "TEST ONLY receipt USD 12.34", "uncertain": False,
                          "approved": True}])

    monkeypatch.setattr("app.documents.ocr._post", post)
    local = extract_document(TEST_ONLY_PNG, "image/png")
    result = await ClaudeVisionOCR(model).extract(TEST_ONLY_PNG, "image/png", local, DocumentLimits())
    assert len(calls) == 1
    url, headers, payload, timeout = calls[0]
    assert url == "https://api.anthropic.com/v1/messages"
    assert headers["x-api-key"] == "TEST-ONLY-KEY"
    assert payload["max_tokens"] == 4096 and timeout == 45
    image = payload["messages"][0]["content"][0]
    assert image["type"] == "image" and image["source"]["media_type"] == "image/png"
    assert base64.b64decode(image["source"]["data"]) == TEST_ONLY_PNG
    assert result["status"] == "extracted_ocr_needs_review"
    assert result["pages"][0]["evidence_state"] == "reported"
    assert result["pages"][0]["requires_human_verification"] is True
    assert "approved" not in result["pages"][0]
    assert result["ocr_provenance"]["provider_request_id"] == "TEST-ONLY-request"
    assert result["ocr_provenance"]["usage"]["input_tokens"] == 100
    assert "TEST-ONLY-KEY" not in json.dumps(result)


@pytest.mark.asyncio
async def test_pdf_native_vision_preserves_original_page_mapping(model, monkeypatch):
    calls = []

    def post(url, headers, payload, timeout):
        calls.append(payload)
        return response([{"page": 2, "text": "TEST ONLY scanned USD 20", "uncertain": True}])

    monkeypatch.setattr("app.documents.ocr._post", post)
    raw = test_pdf_bytes("TEST ONLY digital page", "")
    local = extract_document(raw, "application/pdf")
    # Recognized PDF magic controls the provider media type even when caller sends octet-stream.
    result = await ClaudeVisionOCR(model).extract(raw, "application/octet-stream", local,
                                               DocumentLimits())
    document = calls[0]["messages"][0]["content"][0]
    assert document["type"] == "document"
    assert document["source"]["media_type"] == "application/pdf"
    assert base64.b64decode(document["source"]["data"]) == raw
    assert result["pages"][0] == {"page": 1, "text": "TEST ONLY digital page"}
    assert result["pages"][1]["page"] == 2 and result["pages"][1]["uncertain"] is True
    assert result["ocr_provenance"]["page_numbers"] == [2]


@pytest.mark.asyncio
async def test_provider_and_page_bounds_prevent_network_calls(model, monkeypatch):
    def no_post(*args):
        raise AssertionError("fixture expected no provider request")

    monkeypatch.setattr("app.documents.ocr._post", no_post)
    unsupported = ClaudeVisionOCR(replace(model, api_mode="chat_completions"))
    local = {"status": "needs_ocr", "reason": "ocr_provider_unconfigured", "pages": []}
    result = await unsupported.extract(TEST_ONLY_PNG, "image/png", local, DocumentLimits())
    assert result["reason"] == "ocr_provider_unsupported"
    result = await ClaudeVisionOCR(model).extract(b"%PDF-TEST ONLY", "application/pdf",
        {**local, "page_count": 5}, DocumentLimits())
    assert result["reason"] == "ocr_page_limit"
    result = await ClaudeVisionOCR(model).extract(b"II*\x00TEST ONLY", "image/tiff", local,
                                               DocumentLimits())
    assert result["reason"] == "ocr_content_type_unsupported"


@pytest.mark.asyncio
@pytest.mark.parametrize("pages,stop,reason", [
    ([{"page": 2, "text": "TEST ONLY wrong page", "uncertain": False}], "end_turn",
     "ocr_response_schema_error"),
    ([{"page": True, "text": "TEST ONLY bool page", "uncertain": False}], "end_turn",
     "ocr_response_schema_error"),
    ([{"page": 1, "text": "TEST ONLY", "uncertain": "yes"}], "end_turn",
     "ocr_response_schema_error"),
    ([{"page": 1, "text": "TEST ONLY", "uncertain": False}], "max_tokens",
     "ocr_incomplete_response"),
])
async def test_invalid_response_never_becomes_extracted(model, monkeypatch, pages, stop, reason):
    monkeypatch.setattr("app.documents.ocr._post", lambda *args: response(pages, stop_reason=stop))
    local = {"status": "needs_ocr", "pages": []}
    result = await ClaudeVisionOCR(model).extract(TEST_ONLY_PNG, "image/png", local, DocumentLimits())
    assert result["status"] == "needs_ocr" and result["pages"] == []
    assert result["reason"] == reason
    assert result["ocr_provenance"]["provider_request_id"] == "TEST-ONLY-request"


@pytest.mark.asyncio
async def test_http_error_is_explicit_safe_and_not_retried(model, monkeypatch):
    calls = []

    def fail(*args):
        calls.append(args)
        raise ModelError("provider_http_error", status=429)

    monkeypatch.setattr("app.documents.ocr._post", fail)
    result = await ClaudeVisionOCR(model).extract(TEST_ONLY_PNG, "image/png",
        {"status": "needs_ocr", "pages": []}, DocumentLimits())
    assert len(calls) == 1 and result["status"] == "needs_ocr"
    assert result["ocr_failure"] == {"code": "provider_http_error", "http_status": 429}


@pytest.mark.asyncio
async def test_service_durably_records_ocr_provenance_and_deduplicates_cost(model, monkeypatch):
    from test_documents import MemoryDocumentStore, MemoryDocumentTools

    from app.documents import DocumentService

    store = MemoryDocumentStore()
    tools = MemoryDocumentTools(store)
    calls = []

    def post(*args):
        calls.append(args)
        return response([{"page": 1, "text": "TEST ONLY image receipt", "uncertain": True}])

    monkeypatch.setattr("app.documents.ocr._post", post)
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(model))
    args = {"filename": "test-only.png", "content_type": "image/png", "external_id": "test:photo"}
    first = await service.ingest(TEST_ONLY_PNG, **args)
    second = await service.ingest(TEST_ONLY_PNG, **args)
    assert len(calls) == 1 and second["unchanged"]
    assert len(tools.inference_requests) == len(tools.inference_reservations) == 1
    assert tools.inference_requests[0]["max_model_calls"] == 1
    artifact = tools.artifacts[first["extraction_artifact_path"]]
    assert artifact["extraction"]["ocr_provenance"]["response_id"] == "TEST-ONLY-response"
    assert artifact["extraction"]["requires_human_verification"] is True
    assert artifact["provenance"]["evidence_state"] == "reported"
    assert "claude-vision-v1" in artifact["provenance"]["extractor_version"]
    assert await service.read_raw(first["document_id"]) == TEST_ONLY_PNG


@pytest.mark.asyncio
async def test_service_budget_refusal_preserves_original_and_never_calls_ocr(model, monkeypatch):
    from test_documents import MemoryDocumentStore, MemoryDocumentTools

    from app.documents import DocumentService

    store = MemoryDocumentStore()
    tools = MemoryDocumentTools(store)
    tools.allow_inference = False

    def forbidden(*args):
        raise AssertionError("Refused reservation must never reach an OCR provider")

    monkeypatch.setattr("app.documents.ocr._post", forbidden)
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(model))
    args = {"filename": "test-only-refused.png", "content_type": "image/png",
            "external_id": "test:refused"}
    first = await service.ingest(TEST_ONLY_PNG, **args)
    assert first["extraction_status"] == "needs_ocr"
    assert first["extraction_reason"] == "run_model_call_budget_exhausted"
    assert await service.read_raw(first["document_id"]) == TEST_ONLY_PNG
    artifact = tools.artifacts[first["extraction_artifact_path"]]
    assert artifact["extraction"]["pages"] == []
    assert artifact["extraction"]["ocr_inference_reservation"]["claimed"] is False
    assert (await service.ingest(TEST_ONLY_PNG, **args))["unchanged"]
    assert len(tools.inference_requests) == 1 and not tools.inference_reservations


@pytest.mark.asyncio
async def test_service_four_page_preflight_never_reserves_or_calls_provider(model, monkeypatch):
    from test_documents import MemoryDocumentStore, MemoryDocumentTools

    from app.documents import DocumentService

    store = MemoryDocumentStore()
    tools = MemoryDocumentTools(store)

    def forbidden(*args):
        raise AssertionError("A five-page scan must never reach an OCR provider")

    monkeypatch.setattr("app.documents.ocr._post", forbidden)
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(model))
    result = await service.ingest(test_pdf_bytes("", "", "", "", ""),
        filename="test-only-five-pages.pdf", content_type="application/pdf", external_id="test:five")
    assert result["extraction_status"] == "needs_ocr" and result["extraction_reason"] == "ocr_page_limit"
    assert tools.inference_requests == []


def test_ocr_policy_cannot_expand_cost_bounds():
    with pytest.raises(ValueError):
        OCRLimits(max_pages=5)
    with pytest.raises(ValueError):
        OCRLimits(max_tokens=4097)
