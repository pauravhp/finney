"""Explicit storage fixtures: amendments preserve history and invalidate review."""
from unittest.mock import AsyncMock
from uuid import uuid4

import pytest

from app.config import Settings
from app.finance.types import FinanceError, Scope
from app.finance.workflows import ingest_uploaded_document


@pytest.mark.asyncio
async def test_revision_links_same_document_and_preserves_prior_evidence(monkeypatch):
    scope = Scope(uuid4(), uuid4())
    case, old, new = (str(uuid4()) for _ in range(3))
    path = f"{scope.organization_id}/{scope.run_id}/uploads/{uuid4()}"
    job = {"id": str(uuid4()), "organization_id": str(scope.organization_id),
           "run_id": str(scope.run_id), "requested_by": str(uuid4())}
    payload = {"artifact_path": path, "filename": "amended.txt", "content_type": "text/plain",
               "size": 3, "case_id": case, "replaces_source_id": old}
    prior = {"id": case, "version": 2, "title": "Vendor quote", "status": "open",
             "data": {"source_ids": [old], "source_refs": [{"id": old, "version": 1}],
                      "finding": {"decision": "prior_review"}}}
    source = {"id": old, "external_id": "document:upload:original", "version": 1}
    tools, db = AsyncMock(scope=scope, prepare_only=False), AsyncMock()
    writes = []
    reads = 0
    async def call(name, args):
        nonlocal reads
        if name == "get_case":
            reads += 1
            return {**prior, "version": 2 if reads == 1 else 3}
        if name == "record_case":
            writes.append(args)
            return {"id": case}
        raise AssertionError(name)
    tools.call.side_effect = call
    async def select(table, **kw):
        if table == "memberships": return [{"role": "director"}]
        assert kw["filters"]["run_id"] == "eq." + job["run_id"]
        return [source]
    db.select.side_effect = select
    db.download.return_value = b"new"
    ingest = AsyncMock(return_value={"source_id": new, "source_ref": {"id": new, "version": 2},
                                    "extraction_status": "extracted"})
    monkeypatch.setattr("app.documents.DocumentService.ingest", ingest)
    settings = Settings(_env_file=None, finance_model_api_key="explicit-test-key")
    result = await ingest_uploaded_document(settings, tools, db, payload, job)
    assert result["case_id"] == case
    assert ingest.call_args.kwargs["external_id"] == "upload:original"
    assert ingest.call_args.kwargs["expected_current_source_id"] == old
    assert writes[0]["expected_version"] == 3
    assert writes[0]["status"] == "needs_review"
    assert writes[0]["data"]["source_ids"] == [old, new]
    assert writes[0]["data"]["finding"] == prior["data"]["finding"]
    # A subsequent newer revision prevents stale replacement before ingestion.
    source["id"] = str(uuid4())
    ingest.reset_mock()
    with pytest.raises(FinanceError, match="document_revision_changed"):
        await ingest_uploaded_document(settings, tools, db, payload, job)
    ingest.assert_not_awaited()


@pytest.mark.asyncio
async def test_revision_cannot_attach_a_source_from_another_case():
    scope = Scope(uuid4(), uuid4())
    case = str(uuid4())
    tools, db = AsyncMock(scope=scope), AsyncMock()
    db.select.return_value = [{"role": "director"}]
    tools.call.return_value = {"id": case, "data": {"source_ids": []}}
    job = {"organization_id": str(scope.organization_id), "run_id": str(scope.run_id),
           "requested_by": str(uuid4())}
    with pytest.raises(FinanceError, match="revision_source_not_in_case"):
        await ingest_uploaded_document(None, tools, db, {
            "artifact_path": f"{scope.organization_id}/{scope.run_id}/uploads/{uuid4()}",
            "case_id": case, "replaces_source_id": str(uuid4()),
        }, job)
    db.download.assert_not_awaited()


@pytest.mark.asyncio
async def test_real_ingestor_rejects_revision_arriving_after_outer_preflight():
    """Actual document extraction/storage seam; only the database is an explicit fixture."""
    from copy import deepcopy

    from test_documents import MemoryDocumentStore, MemoryDocumentTools

    from app.documents import ClaudeVisionOCR, DocumentService
    from app.models.providers import ModelConfig

    class Store(MemoryDocumentStore):
        armed = False

        async def select(self, table, *, filters, limit=100):
            if table == "memberships":
                return [{"role": "director"}]
            rows = deepcopy(await super().select(table, filters=filters, limit=limit))
            if self.armed and table == "source_items" and "external_id" in filters:
                self.armed = False
                # The outer latest-source preflight has observed v1; a different
                # completed upload becomes v2 before ingest makes its own read.
                await service.ingest(b"Concurrent newer revision", **args,
                                     expected_current_source_id=old["source_id"])
            return rows

    class Tools(MemoryDocumentTools):
        async def call(self, name, arguments):
            if name == "get_case":
                return deepcopy(case)
            if name == "record_case":
                pytest.fail("Stale upload must not bind another revision to the case")
            return await super().call(name, arguments)

    store = Store()
    tools = Tools(store)
    settings = Settings(_env_file=None, finance_model_api_key="explicit-test-key")
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(ModelConfig.from_settings(settings)))
    args = {"filename": "quote.txt", "content_type": "text/plain", "external_id": "upload:original"}
    old = await service.ingest(b"Original quote", **args)
    case = {"id": str(uuid4()), "version": 1, "title": "Quote", "status": "open",
            "data": {"source_ids": [old["source_id"]], "source_refs": [old["source_ref"]]}}
    scope = tools.scope
    path = f"{scope.organization_id}/{scope.run_id}/uploads/{uuid4()}"
    store.objects[path] = b"Stale replacement"
    job = {"id": str(uuid4()), "organization_id": str(scope.organization_id),
           "run_id": str(scope.run_id), "requested_by": str(uuid4())}
    store.armed = True
    with pytest.raises(FinanceError, match="document_revision_changed"):
        await ingest_uploaded_document(settings, tools, store, {
            "artifact_path": path, "filename": "quote.txt", "content_type": "text/plain",
            "size": len(store.objects[path]), "case_id": case["id"],
            "replaces_source_id": old["source_id"],
        }, job)
    assert [row["version"] for row in store.rows["source_items"]] == [1, 2]
    assert all(raw != b"Stale replacement" for key, raw in store.objects.items() if "/documents/" in key)


@pytest.mark.asyncio
async def test_expected_source_allows_exact_replay_but_rejects_same_bytes_with_changed_metadata():
    from test_documents import MemoryDocumentStore, MemoryDocumentTools

    from app.documents import DocumentService

    store = MemoryDocumentStore()
    service = DocumentService(MemoryDocumentTools(store), store)
    args = {"filename": "quote.txt", "content_type": "text/plain", "external_id": "upload:retry"}
    old = await service.ingest(b"Old quote", **args)
    revised = await service.ingest(b"Current quote", **args, expected_current_source_id=old["source_id"])
    replay = await service.ingest(b"Current quote", **args, expected_current_source_id=old["source_id"])
    assert replay["source_id"] == revised["source_id"] and replay["unchanged"] is True
    objects = dict(store.objects)
    with pytest.raises(FinanceError, match="document_revision_changed"):
        await service.ingest(b"Current quote", **{**args, "content_type": "text/csv"},
                             expected_current_source_id=old["source_id"])
    with pytest.raises(FinanceError, match="document_revision_changed"):
        await service.ingest(b"Current quote", **args, retry_extraction=True,
                             expected_current_source_id=old["source_id"])
    assert store.objects == objects
    assert len(store.rows["source_items"]) == 2
