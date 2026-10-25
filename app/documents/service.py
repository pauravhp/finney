"""Trusted worker seam for Gmail attachments and direct uploads, never an actor write tool."""

from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import asdict
from typing import Any
from uuid import NAMESPACE_URL, uuid5

from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError
from app.storage.supabase import SupabaseClient, SupabaseError

from .extraction import DocumentLimits, extract_document, extractor_version


class DocumentService:
    """Call only after trusted scope/auth validation; it never creates financial effects."""

    def __init__(self, tools: FinanceToolClient, db: SupabaseClient, encryption_key: str = "",
                 *, limits: DocumentLimits | None = None, ocr: Any = None):
        if tools.prepare_only:
            raise FinanceError("evaluation cannot ingest documents")
        self.tools, self.db = tools, db
        self.scope = {"organization_id": str(tools.scope.organization_id),
                      "run_id": str(tools.scope.run_id)}
        self.filters = {key: "eq." + value for key, value in self.scope.items()}
        self.prefix = f"{self.scope['organization_id']}/{self.scope['run_id']}/documents/"
        self.limits = limits or DocumentLimits()
        self.ocr = ocr

    async def _raw(self, path: str, raw: bytes, content_type: str) -> None:
        try:
            await self.db.upload("finance-artifacts", path, raw, content_type)
        except SupabaseError as exc:
            if exc.status not in {400, 409}:
                raise
            existing = await self.db.download("finance-artifacts", path)
            if hashlib.sha256(existing).digest() != hashlib.sha256(raw).digest():
                raise FinanceError("raw document collision") from exc

    async def ingest(self, content: bytes, *, filename: str, content_type: str,
                     external_id: str, parent_source_id: str | None = None,
                     retry_extraction: bool = False) -> dict[str, Any]:
        if not isinstance(content, bytes) or not content or len(content) > self.limits.max_bytes:
            raise ValueError("document must contain 1 to configured maximum bytes")
        if not isinstance(external_id, str) or not 1 <= len(external_id) <= 512:
            raise ValueError("bounded external document identity required")
        if not isinstance(content_type, str) or not 1 <= len(content_type) <= 128:
            raise ValueError("bounded document content type required")
        if not isinstance(filename, str) or not filename:
            raise ValueError("document filename required")
        parent_ref = None
        if parent_source_id:
            parents = await self.db.select("source_items", filters={
                **self.filters, "id": "eq." + str(parent_source_id)}, limit=1)
            if not parents:
                raise FinanceError("parent source outside document scope")
            parent_ref = {"id": parents[0]["id"], "version": parents[0]["version"],
                          "content_sha256": parents[0]["content_sha256"]}
        identity = "document:" + external_id
        digest = hashlib.sha256(content).hexdigest()
        version_tag = extractor_version() + (";ocr=" + self.ocr.version if self.ocr else ";ocr=none")
        policy = asdict(self.limits)
        policy_hash = hashlib.sha256(json.dumps(policy, sort_keys=True).encode()).hexdigest()
        prior = await self.db.select("source_items", filters={
            **self.filters, "external_id": "eq." + identity, "order": "version.desc"}, limit=1)
        latest = prior[0] if prior else None
        same = bool(not retry_extraction and latest
                    and latest.get("metadata", {}).get("document_sha256") == digest
                    and latest["metadata"].get("extractor_version") == version_tag
                    and latest["metadata"].get("extraction_policy_sha256") == policy_hash
                    and latest["metadata"].get("content_type") == content_type
                    and latest["metadata"].get("parent_source_id") == parent_source_id)
        version = int(latest["version"]) if same else int(latest["version"]) + 1 if latest else 1
        external_hash = hashlib.sha256(identity.encode()).hexdigest()
        raw_path = f"{self.prefix}{external_hash}/{version}/{digest}/original"
        # Always ensure raw durability, even when recovering a partially completed attempt.
        await self._raw(raw_path, content, content_type)
        if same:
            source_id = latest["id"]
            extraction_status = latest["metadata"]["extraction_status"]
            extraction_reason = latest["metadata"].get("extraction_reason")
        else:
            extraction = await asyncio.to_thread(
                extract_document, content, content_type, limits=self.limits)
            if self.ocr and extraction["status"] in {"needs_ocr", "partial_needs_ocr"}:
                blocked = self.ocr.blocked_reason(content, content_type, extraction, self.limits)
                if blocked:
                    extraction = {**extraction, "reason": blocked}
                else:
                    # Stable idempotency namespace retained to prevent duplicate OCR reservations.
                    reservation_id = str(uuid5(NAMESPACE_URL, "finny:document-ocr:" + json.dumps(
                        [self.scope["organization_id"], self.scope["run_id"], identity, version,
                         version_tag, policy_hash, digest], separators=(",", ":"),
                    )))
                    reservation = await self.tools.call("reserve_run_inference", {
                        "reservation_id": reservation_id, "max_model_calls": 1,
                    })
                    claimed = isinstance(reservation, dict) and reservation.get("claimed") is True
                    if claimed:
                        extraction = await self.ocr.extract(
                            content, content_type, extraction, self.limits)
                    else:
                        extraction = {**extraction, "reason": (
                            reservation.get("reason") if isinstance(reservation, dict) else None
                        ) or "ocr_inference_reservation_not_claimed"}
                    extraction = {**extraction, "ocr_inference_reservation": {
                        "reservation_id": reservation_id, "max_model_calls": 1,
                        "claimed": claimed, "reason": None if claimed else extraction["reason"],
                    }}
            provenance = {
                "document_sha256": digest, "byte_count": len(content),
                "extractor_version": version_tag, "extraction_policy": policy,
                "extraction_policy_sha256": policy_hash, "parent_source_id": parent_source_id,
                "parent_source_ref": parent_ref,
                "filename": filename.replace("\x00", "")[:200], "content_type": content_type,
                "raw_artifact_path": raw_path,
                "evidence_state": "reported", "authority": "untrusted_source_content",
            }
            artifact = await self.tools.call("put_artifact", {
                "name": "document-extraction.json", "content_type": "application/json",
                "content": json.dumps({"provenance": provenance, "extraction": extraction},
                                      sort_keys=True),
            })
            extraction_status = extraction["status"]
            extraction_reason = extraction.get("reason")
            source_key = hashlib.sha256(json.dumps(
                [identity, version, digest, policy_hash, version_tag],
                separators=(",", ":"),
            ).encode()).hexdigest()
            source = await self.tools.call("record_source", {
                "external_id": identity, "version": version, "source_type": "document",
                "content_sha256": artifact["content_sha256"],
                "artifact_path": artifact["artifact_path"],
                "metadata": {**provenance, "extraction_status": extraction_status,
                             "extraction_reason": extraction_reason},
                "idempotency_key": "document:" + source_key,
            })
            source_id = source["id"]
        document_id = str(uuid5(NAMESPACE_URL, raw_path))
        documents = await self.db.select("documents", filters={
            **self.filters, "artifact_path": "eq." + raw_path}, limit=1)
        if documents:
            document = documents[0]
            if document["content_sha256"] != digest or str(document["source_id"]) != str(source_id):
                raise FinanceError("document record collision")
            document_id = document["id"]
        else:
            try:
                await self.db.insert("documents", {**self.scope, "id": document_id,
                    "source_id": source_id, "artifact_path": raw_path,
                    "content_sha256": digest, "content_type": content_type})
            except SupabaseError as exc:
                if exc.status != 409:
                    raise
                recovered = await self.db.select("documents", filters={
                    **self.filters, "id": "eq." + document_id}, limit=1)
                if not recovered or recovered[0]["content_sha256"] != digest:
                    raise FinanceError("document persistence collision") from exc
        return {"source_id": source_id, "document_id": document_id, "version": version,
                "source_ref": {"id": source_id, "version": version},
                "status": "unchanged" if same else "recorded", "unchanged": same,
                "extraction_status": extraction_status, "extraction_reason": extraction_reason,
                "raw_sha256": digest, "raw_artifact_path": raw_path,
                "extraction_artifact_path": (latest["artifact_path"] if same
                                             else artifact["artifact_path"]),
                "evidence_state": "reported"}

    async def read_raw(self, document_id: str) -> bytes:
        """Trusted download adapter only. Never advertise this method to finance actors."""
        rows = await self.db.select("documents", filters={
            **self.filters, "id": "eq." + str(document_id)}, limit=1)
        if not rows:
            raise FinanceError("document outside bound run")
        record = rows[0]
        path = record["artifact_path"]
        if not path.startswith(self.prefix) or any(p in {".", ".."} for p in path.split("/")):
            raise FinanceError("document path outside bound run")
        raw = await self.db.download("finance-artifacts", path)
        if hashlib.sha256(raw).hexdigest() != record["content_sha256"]:
            raise FinanceError("raw document hash mismatch")
        return raw
