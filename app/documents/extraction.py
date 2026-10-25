"""Bounded local extraction without launching attachment content or external tools."""

from __future__ import annotations

import csv
import importlib.metadata
import io
import logging
import multiprocessing
import os
from dataclasses import asdict, dataclass
from typing import Any

# Persisted extractor identifier; keep its legacy spelling to avoid re-OCR/rebilling.
EXTRACTION_VERSION = "finny-documents-v1"


@dataclass(frozen=True)
class DocumentLimits:
    max_bytes: int = 5 * 1024 * 1024
    max_pages: int = 40
    max_characters: int = 200_000
    max_page_characters: int = 50_000
    max_csv_rows: int = 10_000
    max_csv_columns: int = 100
    timeout_seconds: float = 12
    cpu_seconds: int = 8
    memory_bytes: int = 384 * 1024 * 1024

    def __post_init__(self) -> None:
        for value in asdict(self).values():
            if isinstance(value, bool) or not isinstance(value, (int, float)) or value <= 0:
                raise ValueError("document limits must be positive")
        if self.max_bytes > 5 * 1024 * 1024 or self.max_characters > 200_000:
            raise ValueError("document limits exceed protected storage/output bounds")


def extractor_version() -> str:
    try:
        version = importlib.metadata.version("pypdf")
    except importlib.metadata.PackageNotFoundError:
        version = "unavailable"
    return f"{EXTRACTION_VERSION};pypdf={version}"


def _result(status: str, reason: str | None = None, **kwargs: Any) -> dict:
    return {"status": status, "reason": reason, "pages": [], **kwargs}


def _extract(raw: bytes, kind: str, limits: DocumentLimits) -> dict:
    if kind == "pdf":
        try:
            from pypdf import PdfReader
        except ImportError:
            return _result("blocked", "pdf_dependency_unavailable")
        # Library diagnostics can contain source text; only sanitized statuses leave this process.
        logging.disable(logging.CRITICAL)
        reader = PdfReader(io.BytesIO(raw), strict=True)
        if reader.is_encrypted:
            return _result("blocked", "password_protected_pdf")
        count = len(reader.pages)
        if count > limits.max_pages:
            return _result("rejected", "page_limit", page_count=count)
        if count == 0:
            return _result("failed", "empty_pdf", page_count=0)
        pages, total, missing = [], 0, []
        for number, page in enumerate(reader.pages, 1):
            text = (page.extract_text() or "").strip()
            total += len(text)
            if len(text) > limits.max_page_characters or total > limits.max_characters:
                return _result("rejected", "text_limit", page_count=count)
            if not text:
                missing.append(number)
            pages.append({"page": number, "text": text})
        return _result(
            "needs_ocr" if len(missing) == count else "partial_needs_ocr" if missing else "extracted",
            "ocr_provider_unconfigured" if missing else None,
            pages=pages, page_count=count, missing_text_pages=missing,
            method="pypdf_text", character_count=total,
        )
    if kind == "image":
        return _result("needs_ocr", "ocr_provider_unconfigured", method="none")
    text = raw.decode("utf-8-sig")
    if "\x00" in text:
        return _result("rejected", "binary_text")
    if len(text) > limits.max_characters:
        return _result("rejected", "text_limit")
    if kind == "csv":
        rows = []
        for number, row in enumerate(csv.reader(io.StringIO(text), strict=True), 1):
            if number > limits.max_csv_rows or len(row) > limits.max_csv_columns:
                return _result("rejected", "csv_dimension_limit")
            # Formula-like cells remain strings. No spreadsheet evaluation or monetary coercion.
            rows.append({"row": number, "cells": row})
        return _result("extracted", method="python_csv", rows=rows,
                       pages=[{"page": 1, "text": text}], character_count=len(text))
    return _result("extracted" if text.strip() else "failed", None if text.strip() else "empty_text",
                   method="utf8", pages=[{"page": 1, "text": text}], character_count=len(text))


def _child(send: Any, raw: bytes, kind: str, limits: DocumentLimits) -> None:
    try:
        # Linux worker: hard limits isolate compressed/hostile PDFs from the durable process.
        import resource

        resource.setrlimit(resource.RLIMIT_AS, (limits.memory_bytes, limits.memory_bytes))
        resource.setrlimit(resource.RLIMIT_CPU, (limits.cpu_seconds, limits.cpu_seconds))
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
        send.send(_extract(raw, kind, limits))
    except UnicodeDecodeError:
        send.send(_result("failed", "invalid_utf8"))
    except (MemoryError, OverflowError):
        send.send(_result("rejected", "parser_resource_limit"))
    except Exception:  # noqa: BLE001 - isolate all third-party parser failures at child boundary.
        # Never persist parser exception text, paths or attachment text in operational logs.
        send.send(_result("failed", "invalid_document"))
    finally:
        send.close()


def extract_document(raw: bytes, content_type: str, *, limits: DocumentLimits | None = None) -> dict:
    """Extract in a killable, memory/CPU-bounded process. This function performs no I/O."""
    limits = limits or DocumentLimits()
    if not isinstance(raw, bytes):
        raise TypeError("document content must be bytes")
    if not raw:
        return _result("rejected", "empty_document")
    if len(raw) > limits.max_bytes:
        return _result("rejected", "byte_limit")
    mime = content_type.split(";", 1)[0].strip().lower()
    if raw.startswith(b"%PDF-"):
        kind = "pdf"
    elif mime == "application/pdf":
        return _result("failed", "invalid_pdf_signature")
    elif mime in {"image/png", "image/jpeg", "image/webp", "image/gif", "image/tiff"}:
        signatures = {
            "image/png": raw.startswith(b"\x89PNG\r\n\x1a\n"),
            "image/jpeg": raw.startswith(b"\xff\xd8\xff"),
            "image/webp": raw.startswith(b"RIFF") and raw[8:12] == b"WEBP",
            "image/gif": raw.startswith((b"GIF87a", b"GIF89a")),
            "image/tiff": raw.startswith((b"II*\x00", b"MM\x00*")),
        }
        if not signatures[mime]:
            return _result("failed", "invalid_image_signature")
        kind = "image"
    elif mime in {"text/csv", "application/csv"}:
        kind = "csv"
    elif mime in {"text/plain", "text/markdown"}:
        kind = "text"
    else:
        return _result("unsupported", "unsupported_content_type")
    if os.name != "posix":
        return _result("blocked", "parser_resource_isolation_unavailable")
    context = multiprocessing.get_context("spawn")
    receive, send = context.Pipe(duplex=False)
    process = context.Process(target=_child, args=(send, raw, kind, limits), daemon=True)
    try:
        process.start()
        send.close()
        if not receive.poll(limits.timeout_seconds):
            return _result("rejected", "parser_timeout")
        try:
            return receive.recv()
        except EOFError:
            return _result("rejected", "parser_resource_limit")
    finally:
        receive.close()
        send.close()
        if process.pid:
            if process.is_alive():
                process.kill()
            process.join(timeout=1)
            process.close()
