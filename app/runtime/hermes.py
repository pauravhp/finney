from __future__ import annotations

import ast
import asyncio
import copy
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from pathlib import Path
from typing import Any, Protocol
from uuid import uuid4

from app.models.providers import ModelConfig, ModelError

from .decision_contract import OUTPUT_CONTRACT, validate_decision_shape

APP_ROOT = Path(__file__).resolve().parents[2]
PIN = json.loads((Path(__file__).parent / "hermes-lock.json").read_text())
ACTOR_TOOLS = frozenset(
    {
        "get_case",
        "get_obligations",
        "read_document",
        "search_finance_mail",
        "read_thread",
        "list_due_work",
        "get_financial_position",
        "get_budget_plan",
        "propose_budget_change",
        "calculate_cash_forecast",
        "simulate_commitment",
        "record_finding",
        "propose_obligation_update",
        "create_approval_request",
        "get_approval_status",
        "get_payment_status",
        "generate_financial_report",
        "export_evidence_pack",
    }
)
ONBOARDING_TOOLS = frozenset({"check_setup", "read_setup_step", "record_setup_progress"})


class FinanceTools(Protocol):
    async def call(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]: ...


class HermesActorError(ModelError):
    """Safe public failure plus explicit private artifact input.

    The diagnostic is never in exception args/str/repr. Trusted callers must
    persist it only to private Storage, not ordinary traces or shared logs.
    """

    def __init__(self, code: str, *, private_diagnostic: dict, status: int | None = None):
        super().__init__(code, status=status)
        self._private_diagnostic = copy.deepcopy(private_diagnostic)

    @property
    def private_diagnostic(self) -> dict:
        return copy.deepcopy(self._private_diagnostic)


def _pairs(pairs: list[tuple[str, Any]]) -> dict:
    result = {}
    for key, value in pairs:
        if key in result:
            raise ModelError("model_output_ambiguous_json")
        result[key] = value
    return result


def _constant(value: str) -> None:
    raise ModelError("model_output_not_json_object")


def _loads_object(value: str) -> dict:
    try:
        parsed = json.loads(value, object_pairs_hook=_pairs, parse_constant=_constant)
    except (ValueError, TypeError, RecursionError):
        raise ModelError("model_output_not_json_object") from None
    if not isinstance(parsed, dict):
        raise ModelError("model_output_not_json_object")
    return parsed


def _object_spans(value: str) -> tuple[list[tuple[int, int]], bool]:
    """Linear, bounded framing check; never treats nested objects as alternatives."""
    spans, stack = [], []
    quote = None
    escaped = False
    start = 0
    for index, char in enumerate(value):
        if not stack:
            if char == "{":
                start = index
                stack = ["{"]
            continue
        if quote:
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
            continue
        if char in {"'", '"'}:
            quote = char
        elif char in {"{", "["}:
            stack.append(char)
            if len(stack) > 100:
                return spans, False
        elif char in {"}", "]"}:
            if stack[-1] != ("{" if char == "}" else "["):
                return spans, False
            stack.pop()
            if not stack:
                spans.append((start, index + 1))
                if len(spans) > 1:
                    return spans, True
    return spans, not stack and quote is None


def _without_trailing_commas(value: str) -> str:
    result, quote, escaped = [], None, False
    for index, char in enumerate(value):
        if quote:
            result.append(char)
            if escaped:
                escaped = False
            elif char == "\\":
                escaped = True
            elif char == quote:
                quote = None
        elif char in {"'", '"'}:
            quote = char
            result.append(char)
        elif char == ",":
            following = index + 1
            while following < len(value) and value[following].isspace():
                following += 1
            if following == len(value) or value[following] not in {"}", "]"}:
                result.append(char)
        else:
            result.append(char)
    return "".join(result)


def _json_native(value: Any) -> bool:
    if value is None or type(value) in {str, int, bool}:
        return True
    if isinstance(value, list):
        return all(_json_native(item) for item in value)
    if isinstance(value, dict):
        return all(isinstance(key, str) and _json_native(item) for key, item in value.items())
    # Finance format recovery never coerces floats, tuples, sets or bytes.
    return False


def _actor_output(raw: Any, *, finance: bool) -> tuple[dict, str | None]:
    if not isinstance(raw, str) or not raw.strip() or len(raw.encode("utf-8")) > 2_000_000:
        raise ModelError("model_output_not_json_object")
    spans, complete = _object_spans(raw)
    if len(spans) > 1:
        raise ModelError("model_output_multiple_json_objects")
    if not complete:
        raise ModelError("model_output_incomplete_for_format_recovery")
    fenced = re.findall(r"```json\s*\n?(.*?)```", raw.strip(), re.DOTALL)
    if len(fenced) > 1:
        raise ModelError("model_output_multiple_json_objects")
    stripped = fenced[0].strip() if fenced else raw.strip()
    if not fenced and stripped.startswith("```") and stripped.endswith("```"):
        stripped = stripped[3:-3].strip()
    method = None
    try:
        output = _loads_object(stripped)
    except ModelError as original:
        if original.code != "model_output_not_json_object" or not finance or len(spans) != 1:
            raise
        start, end = spans[0]
        outside = raw[:start] + raw[end:]
        if any(char in outside for char in "{}[]") or raw.strip().startswith(("[", '"', "'")):
            raise ModelError("model_output_not_json_object") from None
        existing = raw[start:end]
        try:
            output = _loads_object(existing)
            method = "single_complete_embedded_json_object"
        except ModelError as embedded:
            if embedded.code != "model_output_not_json_object":
                raise
            try:
                output = _loads_object(_without_trailing_commas(existing))
                method = "complete_json_trailing_comma_normalization"
            except ModelError as malformed:
                if malformed.code != "model_output_not_json_object":
                    raise
                try:
                    literal = ast.parse(existing, mode="eval")
                    if any(isinstance(node, ast.Dict) and len(node.keys) != len({ast.literal_eval(key) for key in node.keys})
                           for node in ast.walk(literal)):
                        raise ModelError("model_output_ambiguous_json")
                    output = ast.literal_eval(literal)
                    if not isinstance(output, dict) or not _json_native(output):
                        raise ValueError
                    method = "complete_python_literal_normalization"
                except (ValueError, TypeError, SyntaxError, RecursionError):
                    raise ModelError("model_output_not_recoverable_without_new_content") from None
    if finance:
        try:
            validate_decision_shape(output)
        except (ValueError, TypeError, AttributeError):
            raise ModelError("invalid_finance_decision_schema") from None
    return output, method


def _known_truncation(result: dict) -> bool:
    if result.get("truncated") is True or result.get("finish_reason") in {"length", "max_tokens", "incomplete"} \
        or result.get("stop_reason") in {"max_tokens", "incomplete"}:
        return True
    reason = result.get("turn_exit_reason")
    return isinstance(reason, str) and any(marker in reason for marker in (
        "finish_reason=length", "finish_reason=incomplete", "partial_stream", "truncat", "iteration_limit", "max_iterations",
    ))


def verify_source(source: Path) -> None:
    if (source / ".env").exists():
        raise ModelError("hermes_source_contains_dotenv")
    for name, digest in PIN["files"].items():
        try:
            actual = hashlib.sha256((source / name).read_bytes()).hexdigest()
        except OSError:
            raise ModelError("hermes_pinned_source_unavailable") from None
        if actual != digest:
            raise ModelError("hermes_source_revision_mismatch")
    tree = hashlib.sha256()
    for path in sorted(p for p in source.rglob("*") if p.is_file()):
        if path.is_symlink():
            raise ModelError("hermes_source_symlink_not_allowed")
        tree.update(
            path.relative_to(source).as_posix().encode()
            + b"\0"
            + hashlib.sha256(path.read_bytes()).digest()
        )
    if tree.hexdigest() != PIN["tree_sha256"]:
        raise ModelError("hermes_source_tree_mismatch")


class HermesActor:
    """One fresh subprocess/profile per job; only a finance registry handler is exposed.

    This is capability isolation for the model, not a host OS security sandbox.
    The pinned runtime is trusted code. Source and dependencies must be installed
    separately; no personal Hermes dotenv/profile is imported.
    """

    def __init__(
        self,
        config: ModelConfig,
        *,
        source: Path | None = None,
        python: str | None = None,
        max_iterations: int = 8,
        timeout_seconds: float = 120,
        mode: str = "finance",
    ):
        if mode not in {"finance", "onboarding"}:
            raise ModelError("invalid_hermes_mode")
        self.mode = mode
        self.config = config
        self.source = (
            source
            or Path(os.getenv("FINANCE_HERMES_SOURCE") or APP_ROOT / ".runtime/hermes-source")
        ).resolve()
        installed_python = APP_ROOT / ".runtime/hermes-venv/bin/python"
        self.python = (
            python
            or os.getenv("FINANCE_HERMES_PYTHON")
            or (str(installed_python) if installed_python.exists() else sys.executable)
        )
        self.max_iterations = max_iterations
        self.timeout_seconds = timeout_seconds

    async def run(
        self,
        prompt: dict,
        skill: str,
        tools: FinanceTools,
        *,
        allowed_tools: frozenset[str] | None = None,
        policy: dict | None = None,
        max_model_calls: int | None = None,
    ) -> dict:
        verify_source(self.source)
        conversation = self.mode == "finance" and prompt.get("command_type") == "director_message"
        mode_tools = ACTOR_TOOLS if self.mode == "finance" else ONBOARDING_TOOLS
        if conversation:
            mode_tools = mode_tools - {"record_finding"}
        allowed_tools = mode_tools if allowed_tools is None else allowed_tools & mode_tools
        if type(self.max_iterations) is not int or self.max_iterations < 1 \
            or (max_model_calls is not None and (type(max_model_calls) is not int or max_model_calls < 1)):
            raise ModelError("evaluation_model_call_budget_exhausted")
        limit = (
            self.max_iterations
            if max_model_calls is None
            else min(self.max_iterations, max_model_calls)
        )
        if type(limit) is not int or limit < 1:
            raise ModelError("evaluation_model_call_budget_exhausted")
        started = time.perf_counter()
        events: list[dict] = []
        output_contract = "finance-director-response-v1" if conversation else OUTPUT_CONTRACT if self.mode == "finance" else "onboarding-v1"
        diagnostic = {"runtime": "hermes", "output_contract": output_contract,
            "original_final_response": None, "tool_events": events, "provider_usage": None,
            "provider_request_ids": [], "api_calls": None, "granted_max_model_calls": limit,
            "format_recovery": {"additional_model_calls": 0, "status": "not_attempted"}}
        with tempfile.TemporaryDirectory(prefix="finance-hermes-") as directory:
            root = Path(directory)
            profile = root / "profile"
            profile.mkdir(mode=0o700)
            # No inherited provider, wallet, mailbox, proxy, plugin or signer credentials.
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": directory,
                "HERMES_HOME": str(profile),
                "PYTHONPATH": str(self.source),
                "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONUNBUFFERED": "1",
                "LANG": "C.UTF-8",
            }
            process = await asyncio.create_subprocess_exec(
                self.python,
                str(Path(__file__).parent / "hermes_worker.py"),
                cwd=directory,
                env=env,
                stdin=asyncio.subprocess.PIPE,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.DEVNULL,
                limit=2_000_000,
            )

            async def send(data: dict) -> None:
                assert process.stdin is not None
                process.stdin.write((json.dumps(data) + "\n").encode())
                await process.stdin.drain()

            await send(
                {
                    "config": {
                        "model": self.config.model,
                        "base_url": self.config.base_url,
                        "api_key": self.config.api_key,
                        "api_mode": self.config.api_mode,
                        "max_tokens": self.config.max_tokens,
                    },
                    "prompt": prompt,
                    "skill": skill,
                    "policy": policy,
                    "allowed_tools": sorted(allowed_tools),
                    "mode": self.mode,
                    "max_iterations": limit,
                    "session_id": str(uuid4()),
                }
            )

            async def converse() -> dict:
                assert process.stdout is not None
                while line := await process.stdout.readline():
                    try:
                        message = json.loads(line)
                    except ValueError:
                        raise ModelError("hermes_protocol_error") from None
                    if message.get("type") == "tool_call":
                        name, arguments = message.get("name"), message.get("arguments")
                        if name not in allowed_tools or not isinstance(arguments, dict):
                            result = {"status": "blocked", "error": "tool_not_permitted"}
                        else:
                            try:
                                result = await tools.call(name, arguments)
                            except Exception as error:  # noqa: BLE001 -- tool boundaries return safe typed failure data.
                                result = {
                                    "status": "failed",
                                    "error": "finance_tool_error",
                                    "error_type": type(error).__name__,
                                }
                        events.append({"name": name, "arguments": arguments, "result": result})
                        await send({"type": "tool_result", "result": result})
                    elif message.get("type") == "result":
                        if message.get("error"):
                            raise ModelError(str(message["error"]))
                        result = message["result"]
                        diagnostic.update(original_final_response=result.get("final_response"),
                            provider_usage=message.get("usage", {}),provider_request_ids=message.get("provider_request_ids", []),
                            api_calls=result.get("api_calls"),completion={key:result.get(key) for key in (
                                "completed","failed","partial","failure_reason","finish_reason","stop_reason","turn_exit_reason","truncated")})
                        if result.get("error"):
                            raise ModelError("hermes_provider_or_runtime_failure")
                        if (
                            result.get("failed")
                            or result.get("partial")
                            or result.get("completed") is not True
                        ):
                            raise ModelError("hermes_incomplete_outcome")
                        calls=result.get("api_calls")
                        if type(calls) is not int or not 0 <= calls <= limit:
                            raise ModelError("hermes_invalid_api_call_count")
                        if _known_truncation(result):
                            raise ModelError("hermes_truncated_output")
                        if conversation:
                            from app.finance.director_response import consulted_source_refs

                            response = result.get("final_response")
                            if not isinstance(response, str) or not response.strip() or len(response) > 16000:
                                raise ModelError("director_response_missing_or_too_large")
                            refs = consulted_source_refs(events)
                            output = {"response_type": "director_response", "message": response,
                                      "evidence_source_ids": [ref["id"] for ref in refs], "consulted_source_refs": refs}
                            recovery = None
                        else:
                            output, recovery = _actor_output(result.get("final_response"), finance=self.mode == "finance")
                        completed = {
                            "output": output,
                            "tool_events": events,
                            "evidence": {
                                "runtime": "hermes",
                                "version": PIN["version"],
                                "revision": PIN["revision"],
                                "model": self.config.model,
                                "output_contract": output_contract,
                                "api_calls": calls,
                                "usage": message.get("usage", {}),
                                "provider_request_ids": message.get("provider_request_ids", []),
                                "latency_seconds": time.perf_counter() - started,
                            },
                        }
                        if recovery:
                            receipt={"method":recovery,"status":"normalized_existing_content","additional_model_calls":0,
                                "original_response_sha256":hashlib.sha256(result["final_response"].encode()).hexdigest(),
                                "normalized_output_sha256":hashlib.sha256(json.dumps(output,sort_keys=True,separators=(",",":"),allow_nan=False).encode()).hexdigest()}
                            diagnostic["format_recovery"]=receipt
                            completed["evidence"]["format_recovery"]=receipt
                            completed["private_diagnostic"]=copy.deepcopy(diagnostic)
                        return completed
                raise ModelError("hermes_process_exited_without_result")

            try:
                remaining=self.timeout_seconds-(time.perf_counter()-started)
                return await asyncio.wait_for(converse(), timeout=max(0,remaining))
            except TimeoutError:
                raise HermesActorError("hermes_timeout",private_diagnostic=diagnostic) from None
            except ModelError as error:
                diagnostic["failure_code"]=error.code
                raise HermesActorError(error.code,status=error.status,private_diagnostic=diagnostic) from None
            finally:
                if process.returncode is None:
                    process.kill()
                await process.wait()
