"""Isolated Hermes actor and the durable-worker entrypoint."""

from .jobs import run_job

__all__ = ["run_job"]
