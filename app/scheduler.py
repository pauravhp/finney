"""Bounded automatic Gmail discovery. This module only queues scoped durable jobs.

It never contacts Gmail, reads/decrypts tokens, changes financial state or invents
an actor. The intake dispatcher rechecks authority before actually using a token.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from datetime import UTC, datetime
from uuid import UUID

from app.storage.supabase import SupabaseClient, SupabaseError

INTERVAL_SECONDS = 60.0


def _uuid(value: object) -> str | None:
    try:
        return str(UUID(str(value)))
    except (ValueError, TypeError, AttributeError):
        return None


def _active_run(run: dict, org: str, run_id: str, now: datetime) -> bool:
    if (
        run.get("organization_id") != org
        or run.get("id") != run_id
        or run.get("status") != "active"
        or run.get("is_demo") is not False
    ):
        return False
    expires = run.get("expires_at")
    if expires is None:
        return True
    try:
        cutoff = datetime.fromisoformat(expires)
        return cutoff.tzinfo is not None and cutoff > now
    except (ValueError, TypeError, AttributeError):
        return False


class GmailIntakeScheduler:
    """One minute cadence plus a round-robin cursor over bounded connection pages."""

    def __init__(
        self,
        *,
        enabled: bool = True,
        batch_size: int = 20,
        monotonic: Callable[[], float] = time.monotonic,
    ):
        if not 1 <= batch_size <= 100:
            raise ValueError("Automatic intake batch size must be between 1 and 100")
        self.enabled, self.batch_size, self.monotonic = enabled, batch_size, monotonic
        self.next_tick = 0.0
        self.cursor: str | None = None

    def delay(self, maximum: float) -> float:
        return (
            min(maximum, max(0.0, self.next_tick - self.monotonic())) if self.enabled else maximum
        )

    async def maybe_enqueue(
        self, db: SupabaseClient, *, now: datetime | None = None
    ) -> dict | None:
        if not self.enabled or self.monotonic() < self.next_tick:
            return None
        # Advance before I/O: an uncertain insert or failed probe is never retried
        # immediately. A later tick recovers through persisted jobs/idempotency.
        self.next_tick = self.monotonic() + INTERVAL_SECONDS
        now = now or datetime.now(UTC)
        if now.tzinfo is None:
            raise ValueError("Scheduler time must be timezone-aware")
        minute = now.astimezone(UTC).strftime("%Y%m%dT%H%MZ")
        filters = {"provider": "eq.gmail", "status": "eq.connected", "order": "id.asc"}
        if self.cursor:
            filters["id"] = "gt." + self.cursor
        rows = await db.select(
            "connections",
            filters=filters,
            columns="id,organization_id,run_id,provider,status,data",
            limit=self.batch_size,
        )
        if not rows and self.cursor:
            self.cursor = None
            filters.pop("id", None)
            rows = await db.select(
                "connections",
                filters=filters,
                columns="id,organization_id,run_id,provider,status,data",
                limit=self.batch_size,
            )
        result = {"scanned": len(rows), "queued": 0, "skipped": 0, "raced": 0}
        for connection in rows:
            # Preserve progress even if a later request times out; no fixed page
            # of early connections can starve the rest of a larger installation.
            self.cursor = _uuid(connection.get("id"))
            outcome = await self._enqueue_connection(db, connection, now, minute)
            result[outcome] += 1
        if len(rows) < self.batch_size:
            self.cursor = None
        return result

    async def _enqueue_connection(
        self, db: SupabaseClient, connection: dict, now: datetime, minute: str
    ) -> str:
        org, run = _uuid(connection.get("organization_id")), _uuid(connection.get("run_id"))
        connection_id = _uuid(connection.get("id"))
        data = connection.get("data")
        if (
            not org
            or not run
            or not connection_id
            or not isinstance(data, dict)
            or connection.get("provider") != "gmail"
            or connection.get("status") != "connected"
        ):
            return "skipped"
        director = _uuid(data.get("connected_by"))
        query = data.get("query")
        if (
            not director
            or not isinstance(query, str)
            or not query.startswith("label:")
            or not query[6:]
            or any(c.isspace() for c in query)
        ):
            return "skipped"
        scope = {"organization_id": "eq." + org, "run_id": "eq." + run}
        runs = await db.select(
            "demo_runs",
            filters={"organization_id": "eq." + org, "id": "eq." + run},
            columns="id,organization_id,status,is_demo,expires_at",
            limit=1,
        )
        if len(runs) != 1 or not _active_run(runs[0], org, run, now):
            return "skipped"
        members = await db.select(
            "memberships",
            filters={
                "organization_id": "eq." + org,
                "user_id": "eq." + director,
                "role": "eq.director",
                "active": "eq.true",
            },
            columns="organization_id,user_id,role,active",
            limit=1,
        )
        if not any(
            row.get("organization_id") == org
            and row.get("user_id") == director
            and row.get("role") == "director"
            and row.get("active") is True
            for row in members
        ):
            return "skipped"
        # Metadata existence only. The scheduler has no reason to retrieve the
        # encrypted token, and cannot copy it into a queued job or logs.
        secrets = await db.select(
            "connector_secrets",
            filters={**scope, "provider": "eq.gmail"},
            columns="organization_id,run_id,provider",
            limit=1,
        )
        if not any(
            row.get("organization_id") == org
            and row.get("run_id") == run
            and row.get("provider") == "gmail"
            for row in secrets
        ):
            return "skipped"
        pending = await db.select(
            "jobs",
            filters={**scope, "command_type": "eq.intake", "status": "in.(queued,running)"},
            columns="id,organization_id,run_id,command_type,status",
            limit=1,
        )
        if any(
            row.get("organization_id") == org
            and row.get("run_id") == run
            and row.get("command_type") == "intake"
            and row.get("status") in {"queued", "running"}
            for row in pending
        ):
            return "skipped"
        values = {
            "organization_id": org,
            "run_id": run,
            "command_type": "intake",
            "payload": {"source": "gmail"},
            "requested_by": director,
            "idempotency_key": f"auto-gmail:{connection_id}:{minute}",
        }
        try:
            await db.insert("jobs", values)
        except SupabaseError as error:
            if error.status != 409:
                raise
            existing = await db.select(
                "jobs",
                filters={**scope, "idempotency_key": "eq." + values["idempotency_key"]},
                columns="organization_id,run_id,command_type,payload,requested_by,idempotency_key",
                limit=1,
            )
            if len(existing) != 1 or any(
                existing[0].get(key) != value for key, value in values.items()
            ):
                raise SupabaseError(409, "auto_intake_idempotency_conflict") from None
            return "raced"
        return "queued"
