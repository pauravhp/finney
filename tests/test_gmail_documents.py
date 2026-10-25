"""Local integration: actual Gmail parser/PDF extraction, explicit HTTP/database fixtures."""

import base64
import copy
import hashlib
from contextlib import asynccontextmanager
from uuid import uuid4

import httpx
import pytest
from cryptography.fernet import Fernet
from test_documents import MemoryDocumentStore, MemoryDocumentTools, test_pdf_bytes

from app.config import Settings
from app.connectors import intake
from app.connectors.errors import ProviderError
from app.connectors.gmail import GmailClient
from app.connectors.tokens import TokenCipher
from app.documents import DocumentService


class IntakeStore(MemoryDocumentStore):
    def __init__(self):
        super().__init__()
        self.rows.update({"cases": [], "connections": [], "connector_secrets": [], "memberships": []})
        self.events = []

    async def select(self, table, *, filters, limit=100):
        def matches(row, key, value):
            if key == "order":
                return True
            actual = row.get("data", {}).get(key.split("->>", 1)[1]) if "->>" in key else row.get(key)
            if isinstance(actual, bool):
                actual = str(actual).lower()
            return str(actual) == value.removeprefix("eq.")

        rows = [row for row in self.rows[table] if all(matches(row, key, value)
                for key, value in filters.items())]
        if filters.get("order") == "version.desc":
            rows.sort(key=lambda row: row["version"], reverse=True)
        return copy.deepcopy(rows[:limit])

    async def update(self, table, values, *, filters):
        matches = await self.select(table, filters=filters)
        ids = {row["id"] for row in matches}
        for row in self.rows[table]:
            if row["id"] in ids:
                row.update(values)
        self.events.append("cursor_advanced" if values.get("status") == "connected" else "blocked")
        return [{**row, **values} for row in matches]


class IntakeTools(MemoryDocumentTools):
    def __init__(self, store):
        super().__init__(store)
        self.fail_binding = False
        self.case_results = {}

    async def call(self, name, arguments):
        if name == "record_case":
            if arguments["idempotency_key"].startswith("mail-attachments:") and self.fail_binding:
                self.fail_binding = False
                raise RuntimeError("TEST ONLY interrupted attachment case binding")
            key = arguments["idempotency_key"]
            if key in self.case_results:
                return self.case_results[key]
            prior = next((row for row in self.store.rows["cases"]
                          if row["id"] == arguments.get("id")), None)
            if prior:
                assert prior["version"] == arguments["expected_version"]
                prior.update({**arguments, "version": prior["version"] + 1})
                row = prior
            else:
                row = {"id": str(uuid4()), "organization_id": str(self.scope.organization_id),
                       "run_id": str(self.scope.run_id), "version": 1, **arguments}
                self.store.rows["cases"].append(row)
            self.store.events.append("case_bound" if key.startswith("mail-attachments:") else "parent_case")
            self.case_results[key] = {"id": row["id"]}
            return {"id": row["id"]}
        if name == "record_trace":
            self.store.events.append("sync_summary")
            return {}
        return await super().call(name, arguments)


@pytest.fixture
def intake_context():
    store = IntakeStore()
    tools = IntakeTools(store)
    user = str(uuid4())
    key = Fernet.generate_key().decode()
    org, run = str(tools.scope.organization_id), str(tools.scope.run_id)
    settings = Settings(_env_file=None, finance_token_encryption_key=key,
                        finance_model_api_key="", finance_gmail_query="label:finance")
    store.rows["connections"] = [{"id": "TEST-ONLY-connection", "organization_id": org,
        "run_id": run, "provider": "gmail", "updated_at": "2026-10-25T00:00:00+00:00",
        "data": {"connected_by": user, "query": "label:finance"}, "status": "connected"}]
    secret = TokenCipher(key).seal({"TEST_ONLY": True}, organization_id=org,
                                    connection_id=run + ":gmail")
    store.rows["connector_secrets"] = [{"organization_id": org, "run_id": run,
        "provider": "gmail", "encrypted_token": secret}]
    store.rows["memberships"] = [{"organization_id": org, "user_id": user,
                                  "role": "director", "active": True}]
    return settings, tools, store


def message(parts, *, message_id="abc123", selected=True):
    return {"id": message_id, "historyId": "20", "labelIds": ["Label_finance"] if selected else [],
            "payload": {"headers": [{"name": "Subject", "value": "TEST ONLY vendor invoice"}],
                        "mimeType": "multipart/mixed", "parts": parts}}


def attachment(filename="test-only.pdf", mime="application/pdf", attachment_id="fixture_pdf", size=0,
               inline=None):
    body = {"size": size}
    if attachment_id:
        body["attachmentId"] = attachment_id
    if inline is not None:
        body["data"] = base64.urlsafe_b64encode(inline).decode()
    return {"filename": filename, "mimeType": mime, "body": body}


def install_http_fixture(monkeypatch, messages, objects, *, failing_attachment=None):
    requests = []

    async def handle(request):
        requests.append(request)
        path = request.url.path
        if path.endswith("/profile"):
            return httpx.Response(200, json={"emailAddress": "TEST-ONLY@example.invalid", "historyId": "20"})
        if path.endswith("/labels"):
            return httpx.Response(200, json={"labels": [{"id": "Label_finance", "name": "finance"}]})
        if path.endswith("/messages"):
            assert request.url.params["labelIds"] == "Label_finance"
            assert request.url.params["q"] == "label:finance"
            return httpx.Response(200, json={"messages": [{"id": row["id"]} for row in messages]})
        if path.endswith("/history"):
            assert request.url.params["labelId"] == "Label_finance"
            return httpx.Response(200, json={"historyId": "20", "history": [{"messagesAdded": [
                {"message": {"id": row["id"]}} for row in messages]}]})
        if "/attachments/" in path:
            identity = path.rsplit("/", 1)[-1]
            if failing_attachment and failing_attachment[0]:
                failing_attachment[0] = False
                return httpx.Response(503)
            raw = objects[identity]
            return httpx.Response(200, json={"size": len(raw),
                "data": base64.urlsafe_b64encode(raw).decode()})
        identity = path.rsplit("/", 1)[-1]
        return httpx.Response(200, json=next(row for row in messages if row["id"] == identity))

    @asynccontextmanager
    async def session(*args):
        async with httpx.AsyncClient(transport=httpx.MockTransport(handle)) as http:
            yield GmailClient(http, "TEST-ONLY-token")

    monkeypatch.setattr(intake, "gmail_session", session)
    return requests


@pytest.mark.asyncio
async def test_selected_gmail_pdf_is_durable_and_bound_before_review_and_cursor(intake_context, monkeypatch):
    settings, tools, store = intake_context
    raw = test_pdf_bytes("TEST ONLY invoice USD 123.45")
    selected = message([attachment(size=len(raw))])
    excluded = message([attachment(attachment_id="forbidden")], message_id="def456", selected=False)
    requests = install_http_fixture(monkeypatch, [selected, excluded], {"fixture_pdf": raw})

    async def reviewed(item):
        case = store.rows["cases"][0]
        assert len(case["data"]["source_ids"]) == 2
        assert case["data"]["source_refs"] == item["source_refs"]
        assert item["attachment_statuses"][0]["extraction_status"] == "extracted"
        assert len(store.rows["documents"]) == 1
        assert next(iter(store.objects.values())) == raw
        store.events.append("review_enqueued")

    result = await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert result["status"] == "completed" and len(result["source_results"]) == 1
    assert store.events == ["parent_case", "case_bound", "review_enqueued", "cursor_advanced", "sync_summary"]
    fetched = [str(request.url) for request in requests if "/attachments/" in request.url.path]
    assert len(fetched) == 1 and "forbidden" not in fetched[0]
    document_source = next(row for row in store.rows["source_items"] if row["source_type"] == "document")
    assert document_source["metadata"]["parent_source_ref"] == result["source_results"][0]["source_ref"] | {
        "content_sha256": next(row["content_sha256"] for row in store.rows["source_items"]
                               if row["source_type"] == "gmail")}


@pytest.mark.asyncio
async def test_retry_after_binding_failure_deduplicates_document_and_preserves_cursor(intake_context, monkeypatch):
    settings, tools, store = intake_context
    raw = test_pdf_bytes("TEST ONLY retry invoice")
    install_http_fixture(monkeypatch, [message([attachment(size=len(raw))])], {"fixture_pdf": raw})
    tools.fail_binding = True
    seen = []

    async def reviewed(item):
        seen.append(item)

    with pytest.raises(RuntimeError, match="interrupted"):
        await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert seen == [] and "cursor_advanced" not in store.events
    assert len(store.rows["documents"]) == 1
    await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert len(seen) == 1 and len(store.rows["documents"]) == 1
    assert len(store.rows["source_items"]) == 2
    case_version = store.rows["cases"][0]["version"]
    await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert seen[-1]["review_key"] == seen[0]["review_key"]
    assert store.rows["cases"][0]["version"] == case_version


@pytest.mark.asyncio
async def test_transient_download_error_never_queues_or_advances_cursor(intake_context, monkeypatch):
    settings, tools, store = intake_context
    raw = test_pdf_bytes("TEST ONLY transient attachment")
    failures = [True]
    install_http_fixture(monkeypatch, [message([attachment(size=len(raw))])],
                         {"fixture_pdf": raw}, failing_attachment=failures)
    seen = []

    async def reviewed(item):
        seen.append(item)

    with pytest.raises(ProviderError) as error:
        await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert error.value.retryable
    assert seen == [] and "cursor_advanced" not in store.events and "blocked" not in store.events
    await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    assert len(seen) == 1 and len(store.rows["documents"]) == 1


@pytest.mark.asyncio
async def test_inline_original_separate_from_parent_and_unsupported_limits_visible(intake_context, monkeypatch):
    settings, tools, store = intake_context
    raw = b"TEST ONLY inline receipt"
    parts = [attachment(filename="test-only.txt", mime="text/plain", attachment_id=None, inline=raw),
             attachment(filename="test-only.exe", mime="application/x-msdownload", attachment_id="forbidden"),
             attachment(attachment_id="too_big", size=6 * 1024 * 1024)]
    requests = install_http_fixture(monkeypatch, [message(parts)], {})
    seen = []

    async def reviewed(item):
        seen.append(item)

    await intake.sync_gmail(settings, tools, store, on_source=reviewed)
    statuses = seen[0]["attachment_statuses"]
    assert [row["extraction_status"] for row in statuses] == ["extracted", "skipped", "skipped"]
    assert statuses[1]["extraction_reason"] == "unsupported_content_type"
    assert statuses[2]["extraction_reason"] == "attachment_byte_limit"
    assert not any("/attachments/" in request.url.path for request in requests)
    parent = next(row for row in store.rows["source_items"] if row["source_type"] == "gmail")
    parent_artifact = tools.artifacts[parent["artifact_path"]]
    assert "inline_data" not in parent_artifact["attachments"][0]
    assert parent_artifact["attachments"][0]["inline_data_sha256"] == hashlib.sha256(
        base64.urlsafe_b64encode(raw)).hexdigest()
    assert next(iter(store.objects.values())) == raw


@pytest.mark.asyncio
async def test_document_factory_is_lazy_and_injectable(intake_context, monkeypatch):
    settings, tools, store = intake_context
    install_http_fixture(monkeypatch, [message([])], {})

    def forbidden(*args):
        pytest.fail("empty message must not initialize parser/model")

    async def reviewed(item):
        return None

    await intake.sync_gmail(settings, tools, store, on_source=reviewed, document_factory=forbidden)
    raw = b"TEST ONLY injected parser factory"
    install_http_fixture(monkeypatch, [message([attachment(filename="test-only.txt", mime="text/plain",
        attachment_id="text_doc", size=len(raw))])], {"text_doc": raw})
    calls = []

    def factory(actual_settings, actual_tools, actual_db):
        calls.append((actual_settings, actual_tools, actual_db))
        return DocumentService(actual_tools, actual_db)

    await intake.sync_gmail(settings, tools, store, on_source=reviewed, document_factory=factory)
    assert calls == [(settings, tools, store)]
