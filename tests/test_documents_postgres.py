"""Actual isolated SQL persistence with a labeled in-memory Storage fixture; no providers."""

import hashlib
import json

import psycopg
import pytest
from psycopg import sql
from psycopg.types.json import Jsonb
from test_documents import TEST_ONLY_PNG, test_pdf_bytes
from test_documents_ocr import response
from test_finance_postgres import (
    database as database,  # noqa: PLC0414 -- pytest fixture registration
)
from test_finance_postgres import identity
from test_finance_postgres import (
    state as state,  # noqa: PLC0414 -- pytest fixture registration
)

from app.documents import ClaudeVisionOCR, DocumentService
from app.finance.tools import FinanceToolClient
from app.finance.types import Scope
from app.models.providers import ModelConfig
from app.storage.supabase import SupabaseError


class SQLDocumentStore:
    """Only object storage is a fixture; source/doc rows and kernel RPC execute actual SQL."""

    def __init__(self, conn):
        self.conn = conn
        self.objects = {}
        self.rpc_operations = []
        self.interrupt_source_once = False

    async def rpc(self, name, args):
        if name == "get_finance_snapshot":
            return self.conn.execute("select public.get_finance_snapshot(%s,%s)", (
                args["p_organization_id"], args["p_run_id"],
            )).fetchone()[0]
        assert name == "finance_kernel_call"
        self.rpc_operations.append(args["p_operation"])
        if args["p_operation"] == "record_source" and self.interrupt_source_once:
            self.interrupt_source_once = False
            raise RuntimeError("TEST ONLY process interruption before source write")
        return self.conn.execute("select public.finance_kernel_call(%s,%s,%s,%s)", (
            args["p_organization_id"], args["p_run_id"], args["p_operation"],
            Jsonb(args["p_arguments"]),
        )).fetchone()[0]

    async def select(self, table, *, filters, limit=100):
        assert table in {"source_items", "documents"}
        clauses, params = [], []
        for key, value in filters.items():
            if key == "order":
                assert value == "version.desc"
                continue
            assert value.startswith("eq.")
            clauses.append(sql.SQL("{}=%s").format(sql.Identifier(key)))
            params.append(value.removeprefix("eq."))
        query = sql.SQL("select to_jsonb(t) from public.{} t where {}{}").format(
            sql.Identifier(table), sql.SQL(" and ").join(clauses),
            sql.SQL(" order by version desc") if "order" in filters else sql.SQL(""),
        ) + sql.SQL(" limit %s")
        return [row[0] for row in self.conn.execute(query, [*params, limit]).fetchall()]

    async def insert(self, table, values):
        assert table == "documents"
        query = sql.SQL("insert into public.{} ({}) values ({}) returning to_jsonb({}.*)").format(
            sql.Identifier(table), sql.SQL(",").join(map(sql.Identifier, values)),
            sql.SQL(",").join(sql.Placeholder() for _ in values), sql.Identifier(table),
        )
        return [self.conn.execute(query, list(values.values())).fetchone()[0]]

    async def upload(self, bucket, path, content, content_type):
        assert bucket == "finance-artifacts"
        if path in self.objects:
            raise SupabaseError(409)
        self.objects[path] = content

    async def download(self, bucket, path):
        assert bucket == "finance-artifacts"
        return self.objects[path]


@pytest.mark.asyncio
async def test_document_ingest_crosses_real_kernel_key_boundary_and_persists_versions(state):
    conn, org, run, _ = state
    store = SQLDocumentStore(conn)
    tools = FinanceToolClient(Scope(org, run), store)
    documents = DocumentService(tools, store)
    raw = test_pdf_bytes("TEST ONLY SQL-backed invoice USD 123.45")
    args = {"filename": "test-only-sql.pdf", "content_type": "application/pdf",
            "external_id": "test-only:" + "x" * 400}
    first = await documents.ingest(raw, **args)
    assert first["extraction_status"] == "extracted"
    assert await documents.read_raw(first["document_id"]) == raw
    source = conn.execute("select artifact_path,metadata from source_items where id=%s",
                          (first["source_id"],)).fetchone()
    assert source[1]["document_sha256"] == hashlib.sha256(raw).hexdigest()
    extracted = await tools.call("read_document", {"source_id": first["source_id"]})
    assert "TEST ONLY SQL-backed invoice USD 123.45" in extracted["content"]
    snapshot = await tools.call("get_finance_snapshot", {})
    projected = next(row for row in snapshot["source_items"] if row["id"] == first["source_id"])
    assert projected["metadata"]["raw_artifact_path"] == first["raw_artifact_path"]
    assert projected["metadata"]["filename"] == "test-only-sql.pdf"
    assert projected["metadata"]["evidence_state"] == "reported"
    assert set(projected["metadata"]) == {
        "filename", "content_type", "raw_artifact_path", "extraction_status",
        "extraction_reason", "parent_source_ref", "document_sha256", "evidence_state",
    }
    assert "extraction_policy" in source[1] and "extraction_policy" not in projected["metadata"]
    second = await documents.ingest(raw, **args)
    assert second["unchanged"] and second["source_ref"] == first["source_ref"]
    changed = await documents.ingest(test_pdf_bytes("TEST ONLY revised USD 130"), **args)
    assert changed["version"] == 2 and changed["source_id"] != first["source_id"]
    assert conn.execute("select count(*) from documents where run_id=%s", (run,)).fetchone()[0] == 2
    keys = conn.execute("select idempotency_key from finance_operations where run_id=%s and operation='record_source'",
                        (run,)).fetchall()
    assert len(keys) == 2 and len({key[0] for key in keys}) == 2
    assert all(key[0].startswith("document:") and len(key[0]) == 73 for key in keys)


@pytest.mark.asyncio
async def test_actual_kernel_rejects_legacy_oversized_document_key(state):
    conn, org, run, _ = state
    tools = FinanceToolClient(Scope(org, run), SQLDocumentStore(conn))
    legacy = f"document:{'a' * 64}:1:{'b' * 64}:{'c' * 64}"
    assert len(legacy) > 200
    with pytest.raises(psycopg.errors.InvalidParameterValue, match="idempotency key"):
        await tools.call("record_source", {"external_id": "TEST ONLY legacy rejected",
            "source_type": "document", "content_sha256": "a" * 64, "idempotency_key": legacy})
    assert conn.execute("select count(*) from source_items where run_id=%s", (run,)).fetchone()[0] == 0


@pytest.mark.asyncio
async def test_actual_sql_refuses_ocr_budget_and_persists_unprocessed_original(state, monkeypatch):
    conn, org, run, _ = state
    conn.execute("reset role")
    conn.execute("insert into finance_run_execution_limits(organization_id,run_id,model_call_limit,reserved_model_calls) values(%s,%s,1,1)", (org, run))
    identity(conn, service=True)
    store = SQLDocumentStore(conn)
    tools = FinanceToolClient(Scope(org, run), store)
    config = ModelConfig("claude-TEST-ONLY", "https://api.anthropic.com/v1", "TEST-ONLY-KEY",
                         api_mode="anthropic_messages")

    def forbidden(*args):
        raise AssertionError("Exhausted SQL budget must prevent all OCR requests")

    monkeypatch.setattr("app.documents.ocr._post", forbidden)
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(config))
    args = {"filename": "test-only-exhausted.png", "content_type": "image/png",
            "external_id": "test:sql-exhausted"}
    first = await service.ingest(TEST_ONLY_PNG, **args)
    assert first["extraction_status"] == "needs_ocr"
    assert first["extraction_reason"] == "run_model_call_budget_exhausted"
    assert await service.read_raw(first["document_id"]) == TEST_ONLY_PNG
    assert (await service.ingest(TEST_ONLY_PNG, **args))["unchanged"]
    assert store.rpc_operations.count("reserve_run_inference") == 1
    conn.execute("reset role")
    assert conn.execute("select count(*) from finance_inference_reservations where run_id=%s", (run,)).fetchone()[0] == 0
    assert conn.execute("select reserved_model_calls from finance_run_execution_limits where run_id=%s", (run,)).fetchone()[0] == 1


@pytest.mark.asyncio
async def test_actual_sql_ocr_reservation_survives_interruption_and_blocks_repeat_spend(state, monkeypatch):
    conn, org, run, _ = state
    store = SQLDocumentStore(conn)
    store.interrupt_source_once = True
    tools = FinanceToolClient(Scope(org, run), store)
    config = ModelConfig("claude-TEST-ONLY", "https://api.anthropic.com/v1", "TEST-ONLY-KEY",
                         api_mode="anthropic_messages")
    calls = []

    def post(*args):
        calls.append(args)
        return response([{"page": 1, "text": "TEST ONLY receipt", "uncertain": False}])

    monkeypatch.setattr("app.documents.ocr._post", post)
    service = DocumentService(tools, store, ocr=ClaudeVisionOCR(config))
    args = {"filename": "test-only-interrupted.png", "content_type": "image/png",
            "external_id": "test:sql-interrupted"}
    with pytest.raises(RuntimeError, match="process interruption"):
        await service.ingest(TEST_ONLY_PNG, **args)
    assert len(calls) == 1
    conn.execute("reset role")
    reserved = conn.execute("select reservation_id,max_model_calls from finance_inference_reservations where run_id=%s", (run,)).fetchall()
    assert len(reserved) == 1 and reserved[0][1] == 1
    identity(conn, service=True)
    resumed = await service.ingest(TEST_ONLY_PNG, **args)
    assert resumed["extraction_reason"] == "inference_reservation_already_consumed"
    assert resumed["extraction_status"] == "needs_ocr" and len(calls) == 1
    assert await service.read_raw(resumed["document_id"]) == TEST_ONLY_PNG
    artifact = await tools.call("read_document", {"source_id": resumed["source_id"]})
    extraction = json.loads(artifact["content"])["extraction"]
    assert extraction["ocr_inference_reservation"]["reservation_id"] == str(reserved[0][0])
    assert extraction["ocr_inference_reservation"]["claimed"] is False
    assert (await service.ingest(TEST_ONLY_PNG, **args))["unchanged"]
    assert store.rpc_operations.count("reserve_run_inference") == 2 and len(calls) == 1
    conn.execute("reset role")
    assert conn.execute("select count(*),sum(max_model_calls) from finance_inference_reservations where run_id=%s", (run,)).fetchone() == (1, 1)
    assert conn.execute("select reserved_model_calls from finance_run_execution_limits where run_id=%s", (run,)).fetchone()[0] == 1
