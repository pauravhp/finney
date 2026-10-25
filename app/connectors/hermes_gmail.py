"""Readonly Gmail through this application's pinned Google Workspace skill."""

from __future__ import annotations

import asyncio
import copy
import json
import os
import signal
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING, Any

from app.models.providers import ModelError
from app.runtime.hermes import APP_ROOT, verify_source

from .errors import ConnectionRequired, ProviderError
from .gmail import GmailClient, HistoryExpired
from .hermes_gmail_worker import (
    MAX_INPUT_BYTES,
    MAX_OUTPUT_BYTES,
    BridgeFailure,
    validate_request,
    validate_token,
)

if TYPE_CHECKING:
    from app.config import Settings


class HermesGmailRuntime:
    """Fresh interpreter and restrictive temporary profile for every operation.

    This is trusted-code capability isolation, not an operating-system sandbox.
    No model, personal Hermes profile, plugin, gws, or inherited secret is used.
    """

    def __init__(
        self,
        settings: Settings,
        *,
        timeout_seconds: float = 45,
        max_output_bytes: int = MAX_OUTPUT_BYTES,
    ):
        self.source = Path(settings.finance_hermes_source or APP_ROOT / ".runtime/hermes-source")
        self.python = str(
            settings.finance_hermes_python or APP_ROOT / ".runtime/hermes-venv/bin/python"
        )
        if self.source.resolve() != (APP_ROOT / ".runtime/hermes-source").resolve():
            raise ConnectionRequired("Configure the application's dedicated pinned Hermes source")
        if os.path.abspath(self.python) != str(APP_ROOT / ".runtime/hermes-venv/bin/python"):
            raise ConnectionRequired("Configure the application's dedicated Hermes interpreter")
        if not 0 < timeout_seconds <= 120 or not 1024 <= max_output_bytes <= MAX_OUTPUT_BYTES:
            raise ValueError("Invalid Gmail runtime limits")
        self.timeout_seconds = timeout_seconds
        self.max_output_bytes = max_output_bytes

    async def request(
        self, operation: str, arguments: dict, credentials: dict | None = None
    ) -> dict:
        try:
            validate_request(operation, arguments, credentials)
            payload = json.dumps(
                {
                    "source": str(self.source.resolve()),
                    "operation": operation,
                    "arguments": arguments,
                    "credentials": credentials,
                },
                allow_nan=False,
            ).encode()
            if len(payload) > MAX_INPUT_BYTES:
                raise BridgeFailure("request_size_limit")
        except (BridgeFailure, ValueError, TypeError):
            raise ProviderError("hermes_gmail_request") from None
        try:
            await asyncio.to_thread(verify_source, self.source)
        except (ModelError, OSError):
            raise ProviderError("hermes_gmail_source") from None
        if not Path(self.python).is_file():
            raise ConnectionRequired("Install the application's dedicated Hermes runtime")
        with tempfile.TemporaryDirectory(prefix="finance-hermes-gmail-") as directory:
            root = Path(directory)
            profile = root / "profile"
            profile.mkdir(mode=0o700)
            config = root / "config"
            config.mkdir(mode=0o700)
            env = {
                "PATH": "/usr/bin:/bin",
                "HOME": directory,
                "HERMES_HOME": str(profile),
                "XDG_CONFIG_HOME": str(config),
                "LANG": "C.UTF-8",
            }
            try:
                process = await asyncio.create_subprocess_exec(
                    self.python,
                    "-I",
                    "-B",
                    str(Path(__file__).with_name("hermes_gmail_worker.py")),
                    cwd=directory,
                    env=env,
                    start_new_session=True,
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.DEVNULL,
                    limit=65_536,
                )
            except OSError:
                raise ProviderError("hermes_gmail_runtime") from None

            async def exchange():
                assert process.stdin is not None and process.stdout is not None
                process.stdin.write(payload)
                await process.stdin.drain()
                process.stdin.close()
                output = bytearray()
                while chunk := await process.stdout.read(65_536):
                    output.extend(chunk)
                    if len(output) > self.max_output_bytes:
                        raise ProviderError("hermes_gmail_output_limit")
                await process.wait()
                if process.returncode != 0:
                    raise ProviderError("hermes_gmail_runtime")
                try:
                    message = json.loads(output)
                except (ValueError, UnicodeDecodeError):
                    raise ProviderError("hermes_gmail_protocol") from None
                if not isinstance(message, dict):
                    raise ProviderError("hermes_gmail_protocol")
                if "error" in message:
                    status = message.get("status")
                    status = status if type(status) is int and 400 <= status <= 599 else None
                    if operation == "get" and arguments["path"] == "/history" and status == 404:
                        raise HistoryExpired()
                    # The worker's raw error text is deliberately never propagated.
                    raise ProviderError(
                        "google_oauth" if operation.startswith("auth_") else "gmail",
                        status,
                        retryable=status == 429 or bool(status and status >= 500),
                    )
                result = message.get("result")
                if not isinstance(result, dict):
                    raise ProviderError("hermes_gmail_protocol")
                if "credentials" in result:
                    try:
                        validate_token(result["credentials"])
                    except BridgeFailure:
                        raise ProviderError("hermes_gmail_protocol") from None
                if operation == "get" and not isinstance(result.get("data"), dict):
                    raise ProviderError("hermes_gmail_protocol")
                return result

            try:
                return await asyncio.wait_for(exchange(), timeout=self.timeout_seconds)
            except TimeoutError:
                raise ProviderError("hermes_gmail_timeout", retryable=True) from None
            except (BrokenPipeError, ConnectionError):
                raise ProviderError("hermes_gmail_runtime") from None
            finally:
                # Also reap any descendant left by trusted upstream code on cancellation.
                try:
                    os.killpg(process.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                await process.wait()


class HermesGmailClient(GmailClient):
    """Retain the existing pagination, label checks, MIME parsing and cursor rules."""

    def __init__(self, runtime: HermesGmailRuntime, credentials: dict[str, Any]):
        try:
            self._credentials = validate_token(credentials)
        except BridgeFailure:
            raise ConnectionRequired(
                "Director must connect the event mailbox through Hermes"
            ) from None
        self._runtime = runtime

    @property
    def credentials(self) -> dict:
        return copy.deepcopy(self._credentials)

    async def _get(self, path: str, params: dict | None = None) -> dict:
        result = await self._runtime.request(
            "get",
            {"path": path, "params": params},
            credentials=self._credentials,
        )
        if "credentials" in result:
            try:
                self._credentials = validate_token(result["credentials"])
            except BridgeFailure:
                raise ProviderError("hermes_gmail_protocol") from None
        return result["data"]
