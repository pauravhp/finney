"""Explicit app-owned installation. Never invoked implicitly by an actor job."""

from __future__ import annotations

import hashlib
import json
import os
import platform
import tarfile
import tempfile
import urllib.request
from pathlib import Path

from app.models.providers import ModelError

PIN = json.loads(Path(__file__).with_name("opencode-lock.json").read_text())
APP_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BINARY = APP_ROOT / ".runtime/opencode/opencode"


def digest(path: Path) -> str:
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def verify_binary(binary: Path) -> None:
    if binary.is_symlink():
        raise ModelError("opencode_binary_symlink_not_allowed")
    try:
        actual = digest(binary)
    except OSError:
        raise ModelError("opencode_pinned_binary_unavailable") from None
    if actual != PIN["binary_sha256"]:
        raise ModelError("opencode_binary_revision_mismatch")


def install(destination: Path = DEFAULT_BINARY) -> dict:
    if platform.system() != "Linux" or platform.machine() not in {"x86_64", "amd64"}:
        raise ModelError("opencode_pinned_platform_unsupported")
    if destination.exists():
        verify_binary(destination)
        return {"runtime": "opencode", "version": PIN["version"], "status": "already_verified"}
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with tempfile.TemporaryDirectory(prefix=".opencode-install-", dir=destination.parent) as directory:
        archive = Path(directory) / PIN["asset"]
        with urllib.request.urlopen(PIN["archive_url"], timeout=120) as response, archive.open("wb") as out:
            while chunk := response.read(1_048_576):
                out.write(chunk)
        if digest(archive) != PIN["archive_sha256"]:
            raise ModelError("opencode_archive_revision_mismatch")
        binary = Path(directory) / "opencode"
        with tarfile.open(archive, "r:gz") as bundle:
            member = bundle.getmember("opencode")
            if not member.isfile() or member.issym() or member.islnk():
                raise ModelError("opencode_archive_invalid")
            source = bundle.extractfile(member)
            if source is None:
                raise ModelError("opencode_archive_invalid")
            with binary.open("wb") as out:
                while chunk := source.read(1_048_576):
                    out.write(chunk)
        verify_binary(binary)
        binary.chmod(0o700)
        os.replace(binary, destination)
    return {"runtime": "opencode", "version": PIN["version"], "revision": PIN["revision"],
            "status": "installed_verified"}


if __name__ == "__main__":
    print(json.dumps(install()))
