"""Obtain the immutable public Hermes source and its isolated locked dependencies.

Run: python -m app.runtime.bootstrap --install
No personal Hermes installation, credentials, plugins or profile are copied.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

from .hermes import APP_ROOT, PIN, verify_source


def bootstrap(*, source: Path, environment: Path, install: bool = False) -> dict:
    source, environment = source.resolve(), environment.resolve()
    source.parent.mkdir(parents=True, exist_ok=True)
    if source.exists():
        verify_source(source)
    else:
        with tempfile.TemporaryDirectory(
            prefix="finance-hermes-fetch-", dir=source.parent
        ) as directory:
            root = Path(directory)
            repository = root / "git"
            git = shutil.which("git")
            if not git:
                raise RuntimeError("git_required_for_public_runtime_bootstrap")
            env = {
                "PATH": os.defpath,
                "HOME": str(root),
                "GIT_CONFIG_GLOBAL": os.devnull,
                "GIT_CONFIG_SYSTEM": os.devnull,
                "GIT_TERMINAL_PROMPT": "0",
            }
            for arguments in (
                [git, "-c", "init.defaultBranch=main", "init", str(repository)],
                [
                    git,
                    "-C",
                    str(repository),
                    "fetch",
                    "--depth=1",
                    PIN["repository"] + ".git",
                    PIN["revision"],
                ],
            ):
                try:
                    result = subprocess.run(
                        arguments, env=env, capture_output=True, timeout=180, check=False
                    )
                except subprocess.TimeoutExpired:
                    raise RuntimeError("public_runtime_fetch_timeout") from None
                if result.returncode:
                    raise RuntimeError("public_runtime_fetch_failed")
            commit = subprocess.run(
                [git, "-C", str(repository), "rev-parse", "FETCH_HEAD"],
                env=env,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.strip()
            if commit != PIN["revision"]:
                raise RuntimeError("public_runtime_revision_mismatch")
            archive = root / "source.tar"
            with archive.open("wb") as output:
                subprocess.run(
                    [git, "-C", str(repository), "archive", commit],
                    env=env,
                    stdout=output,
                    stderr=subprocess.DEVNULL,
                    check=True,
                    timeout=30,
                )
            extracted = root / "source"
            extracted.mkdir()
            with tarfile.open(archive) as tar:
                for member in tar.getmembers():
                    path = Path(member.name)
                    if (
                        path.is_absolute()
                        or ".." in path.parts
                        or member.issym()
                        or member.islnk()
                        or member.isdev()
                    ):
                        raise RuntimeError("unsafe_runtime_archive_member")
                    target = extracted / path
                    if member.isdir():
                        target.mkdir(parents=True, exist_ok=True)
                    elif member.isfile():
                        target.parent.mkdir(parents=True, exist_ok=True)
                        with tar.extractfile(member) as content:
                            target.write_bytes(content.read())
                        target.chmod(member.mode & 0o755)
            verify_source(extracted)
            extracted.rename(source)
    result = {
        "status": "verified",
        "source": str(source),
        "revision": PIN["revision"],
        "environment": str(environment),
        "dependencies_installed": False,
    }
    if install:
        uv = shutil.which("uv")
        if not uv:
            raise RuntimeError("uv_required_for_locked_runtime_dependencies")
        with tempfile.TemporaryDirectory(prefix="finance-hermes-build-") as directory:
            build = Path(directory) / "source"
            shutil.copytree(source, build)
            # Hermes intentionally refuses wheel builds. Install only its locked
            # dependencies; the actor imports the verified source via PYTHONPATH.
            env = {
                "PATH": os.defpath,
                "HOME": directory,
                "UV_PROJECT_ENVIRONMENT": str(environment),
                "PYTHONDONTWRITEBYTECODE": "1",
            }
            command = [
                uv,
                "sync",
                "--frozen",
                "--project",
                str(build),
                "--python",
                sys.executable,
                "--extra",
                "anthropic",
                "--extra",
                "google",
                "--no-dev",
                "--no-install-project",
            ]
            completed = subprocess.run(
                command, env=env, capture_output=True, timeout=600, check=False
            )
            if completed.returncode:
                # The subprocess receives no secrets or private index config.
                # Retain public dependency diagnostics for a concrete repair.
                environment.parent.mkdir(parents=True, exist_ok=True)
                (environment.parent / "hermes-dependency-install.txt").write_text(
                    completed.stderr.decode("utf-8", errors="replace")[-12000:]
                )
                raise RuntimeError("locked_runtime_dependency_install_failed")
        verify_source(source)
        result["dependencies_installed"] = True
        result["python"] = str(environment / "bin/python")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, default=APP_ROOT / ".runtime/hermes-source")
    parser.add_argument("--environment", type=Path, default=APP_ROOT / ".runtime/hermes-venv")
    parser.add_argument("--install", action="store_true")
    arguments = parser.parse_args()
    try:
        result = bootstrap(
            source=arguments.source, environment=arguments.environment, install=arguments.install
        )
    except (RuntimeError, OSError, subprocess.SubprocessError) as error:
        # All RuntimeErrors above use fixed safe codes, never raw provider output.
        result = {
            "status": "blocked",
            "reason": str(error) if isinstance(error, RuntimeError) else type(error).__name__,
        }
    print(json.dumps(result))
    if result["status"] == "blocked":
        raise SystemExit(1)


if __name__ == "__main__":
    main()
