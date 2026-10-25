from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime

from app.config import Settings
from app.documents import ClaudeVisionOCR, DocumentLimits, DocumentService
from app.finance.tools import FinanceToolClient
from app.models.providers import ModelConfig
from app.storage.supabase import SupabaseClient

from .errors import ConnectionRequired, ProviderError
from .gmail import HistoryExpired, decode_body
from .gmail_session import gmail_session
from .tokens import TokenCipher


async def persist_evidence(tools: FinanceToolClient, db: SupabaseClient, evidence: dict) -> dict:
    org, run = str(tools.scope.organization_id), str(tools.scope.run_id)
    external_id = evidence["provider"] + ":" + evidence["external_id"]
    prior = await db.select(
        "source_items",
        filters={
            "organization_id": "eq." + org,
            "run_id": "eq." + run,
            "external_id": "eq." + external_id,
            "order": "version.desc",
        },
        limit=1,
    )
    stable_evidence = {k: v for k, v in evidence.items() if k not in {"content_hash", "history_id"}}
    artifact_content = json.dumps(stable_evidence, sort_keys=True)
    digest = hashlib.sha256(artifact_content.encode()).hexdigest()
    unchanged = bool(prior and prior[0]["content_sha256"] == digest)
    version = int(prior[0]["version"]) if unchanged else int(prior[0]["version"]) + 1 if prior else 1
    if unchanged:
        source = {"id": prior[0]["id"]}
    else:
        artifact = await tools.call(
            "put_artifact",
            {
                "name": f"{evidence['provider']}-evidence.json",
                "content": artifact_content,
                "content_type": "application/json",
            },
        )
        source = await tools.call(
            "record_source",
            {
                "external_id": external_id,
                "version": version,
                "source_type": evidence["provider"],
                "content_sha256": digest,
                "artifact_path": artifact["artifact_path"],
                "metadata": {
                    "evidence_state": "reported",
                    "thread_id": evidence.get("thread_id"),
                    "subject": evidence.get("headers", {}).get("subject"),
                    "mailbox_scope": evidence.get("mailbox_scope"),
                },
                "idempotency_key": f"source:{hashlib.sha256(external_id.encode()).hexdigest()}:{digest}",
            },
        )
    previous_cases = await db.select(
        "cases",
        filters={
            "organization_id": "eq." + org,
            "run_id": "eq." + run,
            "data->>source_external_id": "eq." + external_id,
        },
        limit=1,
    )
    previous = previous_cases[0] if previous_cases else None
    if previous and source["id"] in previous.get("data", {}).get("source_ids", []):
        # Return the case even after an earlier crash: the caller still needs to
        # ensure its durable review job exists before advancing an inbox cursor.
        return {"source_id": source["id"], "source_ref": {"id": source["id"], "version": version},
                "case_id": previous["id"], "status": "unchanged"}
    previous_data = dict(previous.get("data", {})) if previous else {}
    if "finding" in previous_data:
        previous_data.setdefault("superseded_findings", []).append(previous_data.pop("finding"))
    case_args = {
        "title": evidence.get("headers", {}).get("subject")
        or evidence.get("description")
        or "Financial evidence to review",
        "status": "open",
        "data": {
            **previous_data,
            "source_ids": [source["id"]],
            "source_external_id": external_id,
            "superseded_source_ids": (
                previous.get("data", {}).get("superseded_source_ids", [])
                + previous.get("data", {}).get("source_ids", [])
            )
            if previous
            else [],
            "evidence_state": "reported",
        },
        "idempotency_key": f"source-case:{source['id']}",
    }
    if previous:
        case_args.update({"id": previous["id"], "expected_version": previous["version"]})
    case = await tools.call("record_case", case_args)
    return {"source_id": source["id"], "source_ref": {"id": source["id"], "version": version},
            "case_id": case["id"], "status": "recorded"}


MAX_MESSAGE_ATTACHMENTS = 8
MAX_BATCH_ATTACHMENTS = 20
MAX_BATCH_ATTACHMENT_BYTES = 20 * 1024 * 1024
ATTACHMENT_TYPES = {
    "application/pdf", "text/plain", "text/markdown", "text/csv", "application/csv",
    "image/png", "image/jpeg", "image/gif", "image/webp", "image/tiff",
}
EXTENSION_TYPES = {"pdf": "application/pdf", "txt": "text/plain", "md": "text/markdown",
                   "csv": "text/csv", "png": "image/png", "jpg": "image/jpeg",
                   "jpeg": "image/jpeg", "gif": "image/gif", "webp": "image/webp",
                   "tif": "image/tiff", "tiff": "image/tiff"}


def make_document_service(settings: Settings, tools: FinanceToolClient,
                          db: SupabaseClient) -> DocumentService:
    ocr = ClaudeVisionOCR(ModelConfig.from_settings(settings)) if (
        settings.finance_model_api_key.get_secret_value()) else None
    return DocumentService(tools, db, ocr=ocr)


def _attachment_manifest(attachments: list[dict]) -> dict:
    """Keep inline bytes out of the mail JSON; originals belong in private document Storage."""
    manifest = []
    for item in attachments:
        entry = {key: value for key, value in item.items() if key != "inline_data"}
        if item.get("inline_data") is not None:
            inline = item["inline_data"]
            entry["inline_data_sha256"] = hashlib.sha256(
                inline.encode() if isinstance(inline, str) else b"invalid-inline-data").hexdigest()
        manifest.append(entry)
    return {"attachments": manifest[:100], "attachment_count": len(manifest),
            "attachment_manifest_sha256": hashlib.sha256(
                json.dumps(manifest, sort_keys=True).encode()).hexdigest()}


async def _ingest_attachments(gmail, documents: DocumentService, evidence: dict,
                              parent: dict, budget: dict) -> list[dict]:
    outcomes = []
    attachments = evidence.get("attachments", [])
    max_bytes = min(documents.limits.max_bytes, DocumentLimits().max_bytes)
    for index, attachment in enumerate(attachments[:MAX_MESSAGE_ATTACHMENTS]):
        filename = str(attachment.get("filename") or f"attachment-{index + 1}")[:200]
        attachment_id = attachment.get("attachment_id")
        mime = str(attachment.get("mime_type") or "").split(";", 1)[0].strip().lower()
        if mime in {"", "application/octet-stream"}:
            mime = EXTENSION_TYPES.get(filename.rsplit(".", 1)[-1].lower(), mime)
        outcome = {"filename": filename, "attachment_id": attachment_id,
                   "content_type": mime, "evidence_state": "reported"}
        reason = None
        declared_size = attachment.get("size", 0)
        if mime not in ATTACHMENT_TYPES:
            reason = "unsupported_content_type"
        elif type(declared_size) is not int or declared_size < 0:
            reason = "invalid_attachment_size"
        elif declared_size > max_bytes:
            reason = "attachment_byte_limit"
        elif budget["count"] >= MAX_BATCH_ATTACHMENTS:
            reason = "batch_attachment_count_limit"
        elif budget["bytes"] + declared_size > MAX_BATCH_ATTACHMENT_BYTES:
            reason = "batch_attachment_byte_limit"
        if reason:
            outcomes.append({**outcome, "extraction_status": "skipped", "extraction_reason": reason})
            continue
        budget["count"] += 1
        try:
            if attachment.get("inline_data") is not None:
                encoded = attachment["inline_data"]
                if not isinstance(encoded, str) or len(encoded) > ((max_bytes + 2) // 3) * 4 + 4:
                    raise ValueError("bounded inline attachment required")
                raw = decode_body(encoded)
            elif attachment_id:
                raw = await gmail.attachment(evidence["provider_message_id"], attachment_id,
                                             max_bytes=max_bytes)
            else:
                raise ValueError("attachment content unavailable")
        except ValueError:
            outcomes.append({**outcome, "extraction_status": "failed",
                             "extraction_reason": "invalid_or_oversized_attachment"})
            continue
        if not raw or len(raw) > max_bytes:
            outcomes.append({**outcome, "extraction_status": "failed",
                             "extraction_reason": "invalid_or_oversized_attachment"})
            continue
        if budget["bytes"] + len(raw) > MAX_BATCH_ATTACHMENT_BYTES:
            outcomes.append({**outcome, "extraction_status": "skipped",
                             "extraction_reason": "batch_attachment_byte_limit"})
            continue
        budget["bytes"] += len(raw)
        identity = (f"gmail:{evidence['mailbox_scope']}:{evidence['provider_message_id']}:"
                    + (str(attachment_id) if attachment_id else f"inline-{index}"))
        result = await documents.ingest(raw, filename=filename, content_type=mime,
                                        external_id=identity, parent_source_id=parent["source_id"])
        outcomes.append({**outcome, "source_ref": result["source_ref"],
            "document_id": result["document_id"], "raw_sha256": result["raw_sha256"],
            "extraction_status": result["extraction_status"],
            "extraction_reason": result.get("extraction_reason")})
    if len(attachments) > MAX_MESSAGE_ATTACHMENTS:
        outcomes.append({"extraction_status": "skipped", "extraction_reason": "message_attachment_limit",
                         "omitted_count": len(attachments) - MAX_MESSAGE_ATTACHMENTS,
                         "evidence_state": "reported"})
    return outcomes


async def _bind_attachment_case(tools: FinanceToolClient, db: SupabaseClient,
                                parent: dict, outcomes: list[dict]) -> dict:
    source_refs = [parent["source_ref"],
                   *(outcome["source_ref"] for outcome in outcomes if outcome.get("source_ref"))]
    source_ids = [ref["id"] for ref in source_refs]
    bundle = {"source_refs": source_refs, "attachment_statuses": outcomes}
    digest = hashlib.sha256(json.dumps(bundle, sort_keys=True).encode()).hexdigest()
    rows = await db.select("cases", filters={
        "organization_id": "eq." + str(tools.scope.organization_id),
        "run_id": "eq." + str(tools.scope.run_id), "id": "eq." + parent["case_id"]}, limit=1)
    if not rows:
        raise RuntimeError("Persisted mail case missing before attachment binding")
    previous = rows[0]
    previous_data = dict(previous.get("data", {}))
    unchanged = (previous_data.get("source_refs") == source_refs
                 and previous_data.get("attachment_statuses") == outcomes
                 and previous_data.get("source_ids") == source_ids)
    if not unchanged:
        if "finding" in previous_data:
            previous_data.setdefault("superseded_findings", []).append(previous_data.pop("finding"))
        superseded = list(dict.fromkeys(previous_data.get("superseded_source_ids", [])
            + [source for source in previous_data.get("source_ids", []) if source not in source_ids]))
        await tools.call("record_case", {"id": previous["id"],
            "expected_version": previous["version"], "title": previous["title"], "status": "open",
            "data": {**previous_data, **bundle, "source_ids": source_ids,
                     "superseded_source_ids": superseded, "evidence_state": "reported",
                     "intake_status": "complete_with_attachment_outcomes"},
            "idempotency_key": "mail-attachments:" + parent["source_id"] + ":" + digest})
    return {**parent, **bundle, "review_key": "mail-bundle:" + digest,
            "status": "unchanged" if unchanged else "recorded"}


async def sync_gmail(
    settings: Settings,
    tools: FinanceToolClient,
    db: SupabaseClient,
    *,
    on_source: Callable[[dict], Awaitable[None]],
    document_factory: Callable[[Settings, FinanceToolClient, SupabaseClient], DocumentService]
    | None = None,
) -> dict:
    org, run = str(tools.scope.organization_id), str(tools.scope.run_id)
    scoped = {"organization_id": "eq." + org, "run_id": "eq." + run, "provider": "eq.gmail"}
    secrets = await db.select("connector_secrets", filters=scoped)
    connections = await db.select("connections", filters=scoped)
    if not secrets or not connections:
        raise ConnectionRequired("Director must connect the event Gmail mailbox first")
    connection = connections[0]
    data = connection.get("data", {})
    connected_by = data.get("connected_by")
    if not connected_by:
        raise ConnectionRequired("A current director must connect the event mailbox")
    directors = await db.select(
        "memberships",
        filters={
            "organization_id": "eq." + org,
            "user_id": "eq." + str(connected_by),
            "role": "eq.director",
            "active": "eq.true",
        },
        limit=1,
    )
    if not directors:
        raise ConnectionRequired(
            "Mailbox director authority changed; reconnect with a current director"
        )
    query = data.get("query") or settings.finance_gmail_query
    if not re.fullmatch(r"label:[\w./-]+", query):
        raise ValueError("Initial personal-mailbox ingestion requires one explicit finance label")
    cipher = TokenCipher(settings.finance_token_encryption_key.get_secret_value())
    tokens = cipher.open(
        secrets[0]["encrypted_token"], organization_id=org, connection_id=f"{run}:gmail"
    )
    try:
        async with gmail_session(settings, tokens, data) as gmail:
            profile = await gmail.profile()
            mailbox_scope = hashlib.sha256(profile["emailAddress"].casefold().encode()).hexdigest()[:24]
            if data.get("mailbox_scope") not in {None, mailbox_scope}:
                data = {**data, "history_id": None, "label_id": None}
            labels = (await gmail._get("/labels")).get("labels", [])
            matches = [label for label in labels if label["name"] == query.removeprefix("label:")]
            if len(matches) != 1:
                raise ConnectionRequired(
                    "Create the configured finance label and add only intended messages"
                )
            label_id = matches[0]["id"]
            if data.get("label_id") not in {None, label_id}:
                data = {**data, "history_id": None}
            if data.get("history_id"):
                try:
                    batch = await gmail.history_sync(data["history_id"], label_id=label_id)
                except HistoryExpired:
                    batch = await gmail.full_sync(query=query, label_id=label_id)
            else:
                batch = await gmail.full_sync(query=query, label_id=label_id)
            results = []
            documents = None
            attachment_budget = {"count": 0, "bytes": 0}
            for evidence in batch.messages:
                provider_id = evidence["external_id"]
                evidence = {
                    **evidence,
                    "external_id": mailbox_scope + ":" + provider_id,
                    "provider_message_id": provider_id,
                    "mailbox_scope": mailbox_scope,
                }
                attachments = evidence.get("attachments", [])
                if attachments:
                    recorded = await persist_evidence(
                        tools, db, {**evidence, **_attachment_manifest(attachments)})
                    if documents is None:
                        documents = (document_factory or make_document_service)(settings, tools, db)
                    outcomes = await _ingest_attachments(
                        gmail, documents, evidence, recorded, attachment_budget)
                    recorded = await _bind_attachment_case(tools, db, recorded, outcomes)
                else:
                    recorded = await persist_evidence(tools, db, evidence)
                await on_source(recorded)
                results.append(recorded)
            updated_data = {
                **data,
                "history_id": batch.history_id,
                "label_id": label_id,
                "query": query,
                "mailbox_scope": mailbox_scope,
                "last_intake_count": len(results),
            }
            updated = await db.update(
                "connections",
                {
                    "data": updated_data,
                    "status": "connected",
                    "updated_at": datetime.now(UTC).isoformat(),
                },
                filters={**scoped, "updated_at": "eq." + connection["updated_at"]},
            )
            if len(updated) != 1:
                raise ProviderError("gmail_connection_changed", 409, retryable=True)
            summary = {
                "mailbox_scope": mailbox_scope,
                "label_id": label_id,
                "history_id": batch.history_id,
                "source_count": len(results),
                "source_ids": [item["source_id"] for item in results],
            }
            await tools.call(
                "record_trace",
                {
                    "event_type": "gmail_sync_completed",
                    "payload": summary,
                    "idempotency_key": "gmail-sync:"
                    + hashlib.sha256(json.dumps(summary, sort_keys=True).encode()).hexdigest(),
                },
            )
    except ProviderError as error:
        if not error.retryable:
            # Stop the automatic scheduler after a permanent auth/provider failure.
            # A concurrent successful reconnect must not be overwritten.
            await db.update(
                "connections",
                {"status": "blocked", "updated_at": datetime.now(UTC).isoformat()},
                filters={**scoped, "updated_at": "eq." + connection["updated_at"]},
            )
        raise
    return {
        "status": "completed",
        "source_results": results,
        "history_id": batch.history_id,
        "deleted_provider_ids": batch.deleted_ids,
    }
