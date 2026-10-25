"""Ephemeral loopback MCP and metered provider bridge; never a public service."""

from __future__ import annotations

import asyncio
import copy
import hmac
import json
import secrets
from typing import Any, Self

import httpx

from app.models.providers import ModelConfig, ModelError

from .hermes import FinanceTools
from .tool_errors import safe_tool_failure
from .tool_schemas import schema_for

MAX_BYTES = 2_000_000
MAX_PROVIDER_ERROR_BYTES = 65_536


def redact(value: Any, secret_values: tuple[str, ...]) -> Any:
    """Remove known transport secrets even from untrusted provider/tool echoes."""
    if isinstance(value, str):
        for secret in secret_values:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, dict):
        return {redact(k, secret_values): redact(v, secret_values) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, secret_values) for v in value]
    return value


class FinanceBridge:
    """One actor invocation's capabilities, provider allowance and private receipts.

    The child receives a random local token, never the real provider key. Every
    forwarded inference consumes one allowance, including runtime/SDK retries.
    An upstream failure is latched: subsequent retries cannot reach the provider.
    """

    def __init__(
        self, config: ModelConfig, tools: FinanceTools, allowed: frozenset[str],
        limit: int, *, structured: bool, max_tool_calls: int = 64,
    ):
        self.config, self.tools, self.allowed, self.limit = config, tools, allowed, limit
        self.structured, self.max_tool_calls = structured, max_tool_calls
        self.token = secrets.token_urlsafe(32)
        self.events: list[dict] = []
        self.calls: list[dict] = []
        self.failure_code: str | None = None
        self.original_structured_response: str | None = None
        self._private_provider_error: dict | None = None
        self.server: asyncio.Server | None = None
        self.url = ""
        self._tasks: set[asyncio.Task] = set()
        self._model_lock = asyncio.Lock()
        self._tool_lock = asyncio.Lock()
        self._client = httpx.AsyncClient(
            timeout=config.timeout_seconds, follow_redirects=False, trust_env=False,
        )

    def clean(self, value: Any) -> Any:
        return redact(value, (self.config.api_key, self.token))

    async def __aenter__(self) -> Self:
        self.server = await asyncio.start_server(self._accept, "127.0.0.1", 0, limit=MAX_BYTES)
        port = self.server.sockets[0].getsockname()[1]
        self.url = f"http://127.0.0.1:{port}"
        return self

    async def __aexit__(self, *args: object) -> None:
        if self.server:
            self.server.close()
            await self.server.wait_closed()
        for task in tuple(self._tasks):
            task.cancel()
        if self._tasks:
            await asyncio.gather(*tuple(self._tasks), return_exceptions=True)
        await self._client.aclose()

    async def _accept(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter) -> None:
        task = asyncio.current_task()
        self._tasks.add(task)
        try:
            async with asyncio.timeout(self.config.timeout_seconds + 5):
                header = await reader.readuntil(b"\r\n\r\n")
                if len(header) > 16_384:
                    raise ValueError
                lines = header.decode("ascii").split("\r\n")
                method, path, _ = lines[0].split(" ")
                headers = {}
                for line in lines[1:]:
                    if line:
                        key, value = line.split(":", 1)
                        key = key.lower()
                        if key in headers:
                            raise ValueError
                        headers[key] = value.strip()
                # The pinned Bun client sends fixed-length JSON. Reject ambiguous framing.
                if "transfer-encoding" in headers:
                    raise ValueError
                size = int(headers.get("content-length", "0"))
                if not 0 <= size <= MAX_BYTES:
                    raise ValueError
                body = await reader.readexactly(size)
                authorized = headers.get("authorization", "")
                key = headers.get("x-api-key", "")
                if not (hmac.compare_digest(authorized, "Bearer " + self.token)
                        or hmac.compare_digest(key, self.token)):
                    status, content_type, response = 401, "application/json", b'{"error":"unauthorized"}'
                elif method != "POST":
                    status, content_type, response = 405, "application/json", b'{}'
                else:
                    payload = json.loads(body)
                    if not isinstance(payload, dict):
                        raise ValueError
                    status, content_type, response = await self.dispatch(path, payload)
                writer.write(
                    f"HTTP/1.1 {status} Response\r\nContent-Type: {content_type}\r\n"
                    f"Content-Length: {len(response)}\r\nConnection: close\r\n\r\n".encode()
                    + response
                )
                await writer.drain()
        except (ValueError, UnicodeError, asyncio.IncompleteReadError, asyncio.LimitOverrunError):
            writer.write(b"HTTP/1.1 400 Bad Request\r\nContent-Length: 0\r\nConnection: close\r\n\r\n")
        except (OSError, TimeoutError):
            pass
        finally:
            writer.close()
            try:
                await writer.wait_closed()
            except OSError:
                pass
            self._tasks.discard(task)

    async def dispatch(self, path: str, payload: dict) -> tuple[int, str, bytes]:
        if path == "/mcp":
            status, result = await self.mcp(payload)
            return status, "application/json", json.dumps(self.clean(result)).encode()
        expected = "/provider/messages" if self.config.api_mode == "anthropic_messages" else "/provider/chat/completions"
        # The Anthropic SDK may append beta query parameters, never forward them.
        if path.split("?", 1)[0] == expected:
            return await self.provider(payload)
        return 404, "application/json", b'{"error":"route_not_permitted"}'

    async def mcp(self, payload: dict) -> tuple[int, dict]:
        identifier, method = payload.get("id"), payload.get("method")
        if payload.get("jsonrpc") != "2.0":
            return 400, {"error": "invalid_mcp_request"}
        if identifier is None:
            return 202, {}
        result: dict = {}
        if method == "initialize":
            result = {"protocolVersion": "2025-03-26", "capabilities": {"tools": {}},
                      "serverInfo": {"name": "finney-scoped-finance", "version": "1"}}
        elif method == "ping":
            pass
        elif method == "tools/list":
            result = {"tools": [
                {"name": name, "description": schema_for(name)["description"],
                 "inputSchema": schema_for(name)["parameters"]} for name in sorted(self.allowed)
            ]}
        elif method == "tools/call":
            params = payload.get("params")
            params = params if isinstance(params, dict) else {}
            name, arguments = params.get("name"), params.get("arguments", {})
            async with self._tool_lock:
                if not isinstance(name, str) or name not in self.allowed or not isinstance(arguments, dict):
                    response = {"status": "blocked", "error": "tool_not_permitted"}
                elif len(self.events) >= self.max_tool_calls:
                    self.failure_code = "opencode_tool_call_budget_exhausted"
                    response = {"status": "blocked", "error": "tool_call_budget_exhausted"}
                else:
                    try:
                        response = await self.tools.call(name, copy.deepcopy(arguments))
                        # Real get_obligations/list_due_work return arrays. Preserve all
                        # JSON-native results, while rejecting unserializable tool data.
                        json.dumps(response, allow_nan=False)
                    except Exception as error:  # noqa: BLE001 -- never export exception text.
                        response = safe_tool_failure(error)
                event = self.clean({"name": name, "arguments": arguments, "result": response})
                self.events.append(event)
            result = {"content": [{"type": "text", "text": json.dumps(event["result"])}],
                      "isError": isinstance(event["result"], dict)
                      and event["result"].get("status") in {"failed", "blocked"}}
        else:
            return 200, {"jsonrpc": "2.0", "id": identifier,
                         "error": {"code": -32601, "message": "Method not permitted"}}
        return 200, {"jsonrpc": "2.0", "id": identifier, "result": result}

    async def provider(self, payload: dict) -> tuple[int, str, bytes]:
        async with self._model_lock:
            if self.failure_code:
                return self._provider_error(self.failure_code)
            if len(self.calls) >= self.limit:
                self.failure_code = "evaluation_model_call_budget_exhausted"
                return self._provider_error(self.failure_code)
            if payload.get("model") != self.config.model:
                self.failure_code = "opencode_unexpected_model"
                return self._provider_error(self.failure_code)
            permitted = {"finance_" + name for name in self.allowed}
            if self.structured:
                permitted.add("StructuredOutput")
            tool_names = []
            for tool in payload.get("tools", []):
                if not isinstance(tool, dict):
                    self.failure_code = "opencode_unexpected_toolset"
                    return self._provider_error(self.failure_code)
                tool_names.append(tool.get("name", tool.get("function", {}).get("name")))
            if any(name not in permitted for name in tool_names):
                self.failure_code = "opencode_unexpected_toolset"
                return self._provider_error(self.failure_code)
            # Make the existing model config the hard output-token bound, independent of SDK defaults.
            payload = copy.deepcopy(payload)
            payload["max_tokens"] = self.config.max_tokens
            payload.pop("max_completion_tokens", None)
            payload.pop("thinking", None)
            payload.pop("reasoning_effort", None)
            payload["temperature"] = 0
            if self.config.api_mode == "anthropic_messages" and self.config.model == "claude-sonnet-5-5":
                for field in ("temperature", "top_p", "top_k"):
                    payload.pop(field, None)
                payload["thinking"] = {"type": "between_tools"}
                payload["output_config"] = {**payload.get("output_config", {}), "effort": "high"}
                if payload.get("tool_choice", {}).get("type") in {"tool", "any"}:
                    payload["tool_choice"] = {"type": "auto"}
            path = "/messages" if self.config.api_mode == "anthropic_messages" else "/chat/completions"
            headers = ({"x-api-key": self.config.api_key, "anthropic-version": "2023-06-01"}
                       if self.config.api_mode == "anthropic_messages"
                       else {"Authorization": "Bearer " + self.config.api_key})
            receipt = {"index": len(self.calls) + 1, "model": self.config.model,
                       "max_tokens": self.config.max_tokens, "usage": {}, "request_id": None,
                       "finish_reason": None, "status": "started"}
            self.calls.append(receipt)
            try:
                async with self._client.stream(
                    "POST", self.config.base_url.rstrip("/") + path, headers=headers, json=payload,
                ) as response:
                    receipt["http_status"] = response.status_code
                    receipt["request_id"] = self.clean(response.headers.get("request-id")
                                                       or response.headers.get("x-request-id"))
                    if response.status_code != 200:
                        self.failure_code = "provider_http_error"
                        receipt["status"] = "failed"
                        await self._capture_provider_error(response)
                        return self._provider_error(self.failure_code)
                    chunks, total = [], 0
                    async for chunk in response.aiter_bytes():
                        total += len(chunk)
                        if total > MAX_BYTES:
                            raise ModelError("provider_response_too_large")
                        chunks.append(chunk)
                    raw = b"".join(chunks)
                    content_type = response.headers.get("content-type", "application/json")
                    self._capture_usage(receipt, raw, content_type)
                    if self.failure_code:
                        receipt["status"] = "failed"
                        return self._provider_error(self.failure_code)
                    receipt["status"] = "completed"
                    return 200, content_type, raw
            except (httpx.HTTPError, OSError, ModelError) as error:
                self.failure_code = error.code if isinstance(error, ModelError) else "provider_transport_error"
                receipt["status"] = "failed"
                return self._provider_error(self.failure_code)

    async def _capture_provider_error(self, response: httpx.Response) -> None:
        """Read a finite error prefix; only the parent actor's private diagnostic gets it."""
        chunks, total, read_error = [], 0, None
        try:
            async for chunk in response.aiter_bytes(chunk_size=4096):
                remaining = MAX_PROVIDER_ERROR_BYTES + 1 - total
                chunks.append(chunk[:remaining])
                total += min(len(chunk), remaining)
                if total > MAX_PROVIDER_ERROR_BYTES:
                    break
        except (httpx.HTTPError, OSError) as error:
            read_error = type(error).__name__
        finally:
            raw = b"".join(chunks)
            text = raw[:MAX_PROVIDER_ERROR_BYTES].decode("utf-8", errors="replace")
            if len(raw) > MAX_PROVIDER_ERROR_BYTES or read_error:
                # A bounded prefix can end in the middle of a known credential.
                for secret in (self.config.api_key, self.token):
                    for size in range(min(len(secret), len(text)), 0, -1):
                        if text.endswith(secret[:size]):
                            text = text[:-size] + "[REDACTED]"
                            break
            cleaned = self.clean(text)
            encoded = cleaned.encode("utf-8")
            body = encoded[:MAX_PROVIDER_ERROR_BYTES].decode("utf-8", errors="ignore")
            self._private_provider_error = {
                "http_status": response.status_code,
                "body": body, "body_bytes": len(body.encode("utf-8")),
                "truncated": len(raw) > MAX_PROVIDER_ERROR_BYTES or len(encoded) > MAX_PROVIDER_ERROR_BYTES,
                "read_error_type": read_error,
            }

    @property
    def private_provider_error(self) -> dict | None:
        return copy.deepcopy(self._private_provider_error)

    @staticmethod
    def _provider_error(code: str) -> tuple[int, str, bytes]:
        # A 400 is deliberately permanent so OpenCode cannot retry a provider failure.
        return 400, "application/json", json.dumps({"type": "error", "error": {
            "type": "invalid_request_error", "message": code,
        }}).encode()

    def _capture_usage(self, receipt: dict, raw: bytes, content_type: str) -> None:
        try:
            if "text/event-stream" in content_type:
                parts = [json.loads(line[5:].strip()) for line in raw.decode().splitlines()
                         if line.startswith("data:") and line[5:].strip() not in {"", "[DONE]"}]
            else:
                parts = [json.loads(raw)]
            tool_calls: dict[int, dict] = {}
            for part in parts:
                for section in (part, part.get("message", {})):
                    if isinstance(section.get("usage"), dict):
                        receipt["usage"].update(self.clean(section["usage"]))
                reason = part.get("stop_reason") or part.get("delta", {}).get("stop_reason")
                for choice in part.get("choices", []):
                    reason = choice.get("finish_reason") or reason
                    for tool in choice.get("delta", {}).get("tool_calls", []):
                        call = tool_calls.setdefault(tool.get("index", 0), {"name": "", "arguments": ""})
                        function = tool.get("function", {})
                        call["name"] += function.get("name", "")
                        call["arguments"] += function.get("arguments", "")
                    for tool in choice.get("message", {}).get("tool_calls", []):
                        function = tool.get("function", {})
                        tool_calls[len(tool_calls)] = {
                            "name": function.get("name"), "arguments": function.get("arguments", ""),
                        }
                block = part.get("content_block", {})
                if block.get("type") == "tool_use":
                    tool_calls[part.get("index", 0)] = {"name": block.get("name"), "arguments": ""}
                if part.get("delta", {}).get("type") == "input_json_delta":
                    index = part.get("index", 0)
                    if index in tool_calls:
                        tool_calls[index]["arguments"] += part["delta"].get("partial_json", "")
                for tool in part.get("content", []):
                    if tool.get("type") == "tool_use":
                        tool_calls[len(tool_calls)] = {"name": tool.get("name"),
                                                       "arguments": json.dumps(tool.get("input", {}))}
                if reason:
                    receipt["finish_reason"] = reason
                if part.get("type") == "error":
                    self.failure_code = "provider_stream_error"
            permitted = {"finance_" + name for name in self.allowed}
            if self.structured:
                permitted.add("StructuredOutput")
            receipt["tool_names"] = [self.clean(call["name"]) for call in tool_calls.values()]
            for call in tool_calls.values():
                if call["name"] == "StructuredOutput":
                    self.original_structured_response = self.clean(call["arguments"])
                if call["name"] not in permitted:
                    self.failure_code = "opencode_tool_not_permitted"
                    try:
                        arguments = json.loads(call["arguments"])
                    except ValueError:
                        arguments = {"raw_arguments": call["arguments"]}
                    self.events.append(self.clean({
                        "name": call["name"], "arguments": arguments,
                        "result": {"status": "blocked", "error": "tool_not_permitted"},
                    }))
            if "text/event-stream" in content_type:
                complete = any(part.get("type") == "message_stop" for part in parts) or (
                    any(line.strip() == "data: [DONE]" for line in raw.decode().splitlines())
                )
                if not complete or not receipt["finish_reason"]:
                    self.failure_code = self.failure_code or "provider_incomplete_stream"
        except (ValueError, UnicodeError, TypeError, AttributeError):
            self.failure_code = "provider_invalid_json"

    @property
    def usage(self) -> dict:
        total: dict[str, int | float] = {}
        for receipt in self.calls:
            for key, value in receipt["usage"].items():
                if type(value) in {int, float}:
                    total[key] = total.get(key, 0) + value
        return total

    @property
    def request_ids(self) -> list[str]:
        return [call["request_id"] for call in self.calls if call["request_id"]]
