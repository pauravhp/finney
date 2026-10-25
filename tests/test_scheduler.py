"""Automatic-discovery unit fixtures only; these tests make no provider calls."""

from __future__ import annotations

from copy import deepcopy
from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from app.scheduler import GmailIntakeScheduler
from app.storage.supabase import SupabaseError

ORG = "a599baba-8e25-40bb-9ec9-51d5036166d0"
RUN = "631854b5-9112-4daa-929d-e5279ec206d0"
DIRECTOR = "35fd4095-fd94-487c-9c7b-2143407a76d0"
CONNECTION = "0f7a41c2-116b-4587-813c-9ebd7c9166d0"
NOW = datetime(2026, 10, 25, 3, 0, tzinfo=UTC)


def fixture_rows():
    return {
        "connections": [
            {
                "id": CONNECTION,
                "organization_id": ORG,
                "run_id": RUN,
                "provider": "gmail",
                "status": "connected",
                "data": {"connected_by": DIRECTOR, "query": "label:director-finance"},
            }
        ],
        "demo_runs": [
            {
                "id": RUN,
                "organization_id": ORG,
                "status": "active",
                "is_demo": False,
                "expires_at": None,
            }
        ],
        "memberships": [
            {"organization_id": ORG, "user_id": DIRECTOR, "role": "director", "active": True}
        ],
        "connector_secrets": [
            {
                "organization_id": ORG,
                "run_id": RUN,
                "provider": "gmail",
                "encrypted_token": "unit-fixture-not-returned",
            }
        ],
        "jobs": [],
    }


class FixtureDB:
    def __init__(self, rows=None, *, race=False, conflict=False):
        self.rows = deepcopy(rows or fixture_rows())
        self.reads = []
        self.inserts = []
        self.race, self.conflict = race, conflict

    async def select(self, table, *, filters, columns="*", limit=100):
        self.reads.append((table, deepcopy(filters), columns, limit))
        rows = deepcopy(self.rows.get(table, []))
        for key, expression in filters.items():
            if key == "order":
                continue
            if expression.startswith("eq."):
                wanted = expression[3:]
                rows = [row for row in rows if str(row.get(key)).lower() == wanted.lower()]
            elif expression.startswith("gt."):
                rows = [row for row in rows if str(row.get(key)) > expression[3:]]
            elif expression.startswith("in.("):
                wanted = expression[4:-1].split(",")
                rows = [row for row in rows if row.get(key) in wanted]
            else:
                raise AssertionError("Fixture received an unsupported query")
        if "order" in filters:
            field, order = filters["order"].split(".")
            rows.sort(key=lambda row: row[field], reverse=order == "desc")
        rows = rows[:limit]
        if columns != "*":
            rows = [{key: row[key] for key in columns.split(",") if key in row} for row in rows]
        return rows

    async def insert(self, table, values):
        self.inserts.append((table, deepcopy(values)))
        previous = [
            row
            for row in self.rows[table]
            if all(
                row.get(key) == values[key]
                for key in ("organization_id", "run_id", "idempotency_key")
            )
        ]
        if previous:
            raise SupabaseError(409, "fixture_unique_conflict")
        row = {**values, "id": "scheduler-fixture-job", "status": "queued"}
        if self.conflict:
            row["requested_by"] = "different-actor"
        self.rows[table].append(row)
        if self.race or self.conflict:
            raise SupabaseError(409, "fixture_concurrent_insert")
        return [row]


@pytest.mark.asyncio
async def test_connected_director_queues_scoped_gmail_without_reading_token_or_overriding_label():
    db = FixtureDB()
    result = await GmailIntakeScheduler(monotonic=lambda: 0).maybe_enqueue(db, now=NOW)
    assert result == {"scanned": 1, "queued": 1, "skipped": 0, "raced": 0}
    assert db.inserts == [
        (
            "jobs",
            {
                "organization_id": ORG,
                "run_id": RUN,
                "command_type": "intake",
                "payload": {"source": "gmail"},
                "requested_by": DIRECTOR,
                "idempotency_key": f"auto-gmail:{CONNECTION}:20261025T0300Z",
            },
        )
    ]
    secret_reads = [row for row in db.reads if row[0] == "connector_secrets"]
    assert secret_reads[0][2] == "organization_id,run_id,provider"
    assert "unit-fixture-not-returned" not in str(db.inserts)
    assert (
        "query" not in db.inserts[0][1]["payload"]
    )  # existing connection label remains authoritative


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "defect",
    [
        "expired",
        "expiry_equal",
        "invalid_expiry",
        "demo",
        "closed",
        "missing_director",
        "malformed_director",
        "removed_director",
        "inactive_director",
        "wrong_org_member",
        "missing_token",
        "wrong_run_token",
        "missing_label",
        "broad_query",
        "disconnected",
    ],
)
async def test_missing_or_revoked_scope_never_queues_mail(defect):
    rows = fixture_rows()
    if defect == "expired":
        rows["demo_runs"][0]["expires_at"] = (NOW - timedelta(seconds=1)).isoformat()
    elif defect == "expiry_equal":
        rows["demo_runs"][0]["expires_at"] = NOW.isoformat()
    elif defect == "invalid_expiry":
        rows["demo_runs"][0]["expires_at"] = "not-a-cutoff"
    elif defect == "demo":
        rows["demo_runs"][0]["is_demo"] = True
    elif defect == "closed":
        rows["demo_runs"][0]["status"] = "closed"
    elif defect == "missing_director":
        rows["connections"][0]["data"].pop("connected_by")
    elif defect == "malformed_director":
        rows["connections"][0]["data"]["connected_by"] = "anonymous"
    elif defect == "removed_director":
        rows["memberships"][0]["role"] = "finance"
    elif defect == "inactive_director":
        rows["memberships"][0]["active"] = False
    elif defect == "wrong_org_member":
        rows["memberships"][0]["organization_id"] = str(UUID(int=2))
    elif defect == "missing_token":
        rows["connector_secrets"] = []
    elif defect == "wrong_run_token":
        rows["connector_secrets"][0]["run_id"] = str(UUID(int=3))
    elif defect == "missing_label":
        rows["connections"][0]["data"].pop("query")
    elif defect == "broad_query":
        rows["connections"][0]["data"]["query"] = "label:director-finance OR in:inbox"
    elif defect == "disconnected":
        rows["connections"][0]["status"] = "reconnect_required"
    db = FixtureDB(rows)
    result = await GmailIntakeScheduler(monotonic=lambda: 0).maybe_enqueue(db, now=NOW)
    assert result["queued"] == 0 and db.inserts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("status", ["queued", "running"])
async def test_existing_intake_of_any_source_is_not_duplicated(status):
    rows = fixture_rows()
    rows["jobs"] = [
        {
            "id": "fixture-pending",
            "organization_id": ORG,
            "run_id": RUN,
            "command_type": "intake",
            "payload": {"source": "csv"},
            "status": status,
        }
    ]
    db = FixtureDB(rows)
    result = await GmailIntakeScheduler(monotonic=lambda: 0).maybe_enqueue(db, now=NOW)
    assert result["skipped"] == 1 and not db.inserts


@pytest.mark.asyncio
async def test_minute_cadence_and_restart_idempotency_survive_fast_completed_job():
    clock = [0.0]
    scheduler = GmailIntakeScheduler(monotonic=lambda: clock[0])
    db = FixtureDB()
    await scheduler.maybe_enqueue(db, now=NOW)
    reads = len(db.reads)
    clock[0] = 59.9
    assert await scheduler.maybe_enqueue(db, now=NOW) is None
    assert len(db.reads) == reads
    db.rows["jobs"][0]["status"] = "completed"
    restart = GmailIntakeScheduler(monotonic=lambda: 0)
    assert (await restart.maybe_enqueue(db, now=NOW))["raced"] == 1
    assert len(db.rows["jobs"]) == 1
    clock[0] = 60.0
    assert (await scheduler.maybe_enqueue(db, now=NOW + timedelta(minutes=1)))["queued"] == 1
    assert len(db.rows["jobs"]) == 2


@pytest.mark.asyncio
async def test_race_is_verified_but_mismatched_actor_conflict_is_not_success():
    raced = await GmailIntakeScheduler(monotonic=lambda: 0).maybe_enqueue(
        FixtureDB(race=True), now=NOW
    )
    assert raced["raced"] == 1 and raced["queued"] == 0
    db = FixtureDB(conflict=True)
    with pytest.raises(SupabaseError, match="auto_intake_idempotency_conflict"):
        await GmailIntakeScheduler(monotonic=lambda: 0).maybe_enqueue(db, now=NOW)
    assert len(db.inserts) == 1


@pytest.mark.asyncio
async def test_bounded_batches_rotate_across_connections_and_wrap():
    rows = fixture_rows()
    rows["connections"], rows["demo_runs"], rows["connector_secrets"] = [], [], []
    for number in range(1, 4):
        run, connection = str(UUID(int=number + 10)), str(UUID(int=number))
        rows["connections"].append(
            {**fixture_rows()["connections"][0], "id": connection, "run_id": run}
        )
        rows["demo_runs"].append({**fixture_rows()["demo_runs"][0], "id": run})
        rows["connector_secrets"].append({**fixture_rows()["connector_secrets"][0], "run_id": run})
    db, clock = FixtureDB(rows), [0.0]
    scheduler = GmailIntakeScheduler(batch_size=2, monotonic=lambda: clock[0])
    assert (await scheduler.maybe_enqueue(db, now=NOW))["queued"] == 2
    clock[0] = 60
    assert (await scheduler.maybe_enqueue(db, now=NOW + timedelta(minutes=1)))["queued"] == 1
    assert len(db.inserts) == 3
    assert all(read[3] <= 2 for read in db.reads if read[0] == "connections")


@pytest.mark.asyncio
async def test_disabled_discovery_does_not_query_database():
    db = FixtureDB()
    assert await GmailIntakeScheduler(enabled=False).maybe_enqueue(db, now=NOW) is None
    assert db.reads == [] and db.inserts == []


@pytest.mark.asyncio
@pytest.mark.parametrize("enabled", [True, False])
async def test_background_worker_discovers_before_lease_and_respects_disable(
    tmp_path, monkeypatch, enabled
):
    from app.cli import run_worker
    from app.config import Settings

    class StopFixtureWorker(RuntimeError):
        pass

    class ScopedFixtureDB(FixtureDB):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    db = ScopedFixtureDB()

    class FixtureQueue:
        def __init__(self, *args):
            pass

        async def lease(self, **kwargs):
            if enabled:
                assert len(db.inserts) == 1
            else:
                assert db.reads == [] and db.inserts == []
            raise StopFixtureWorker()

    monkeypatch.setattr("app.storage.supabase.SupabaseClient", lambda *args, **kwargs: db)
    monkeypatch.setattr("app.finance.jobs.JobQueue", FixtureQueue)
    settings = Settings(
        _env_file=None,
        supabase_url="https://fixture.invalid",
        supabase_secret_key="fixture-only",
        finance_auto_intake_enabled=enabled,
    )
    with pytest.raises(StopFixtureWorker):
        await run_worker(settings)


@pytest.mark.asyncio
async def test_background_auth_failure_stops_after_one_read_without_leasing_or_status_write(
    tmp_path, monkeypatch
):
    from app.cli import run_worker
    from app.config import Settings

    class RejectedFixtureDB(FixtureDB):
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def select(self, *args, **kwargs):
            self.reads.append("authorization_attempt")
            raise SupabaseError(401, "fixture_auth_rejected")

    db = RejectedFixtureDB()

    class FixtureQueue:
        def __init__(self, *args):
            pass

        async def lease(self, **kwargs):
            pytest.fail("Authorization failure must stop before another service request")

    monkeypatch.setattr("app.storage.supabase.SupabaseClient", lambda *args, **kwargs: db)
    monkeypatch.setattr("app.finance.jobs.JobQueue", FixtureQueue)
    settings = Settings(
        _env_file=None,
        supabase_url="https://fixture.invalid",
        supabase_secret_key="fixture-only",
        finance_auto_intake_enabled=True,
    )
    with pytest.raises(SupabaseError, match="fixture_auth_rejected"):
        await run_worker(settings)
    assert db.reads == ["authorization_attempt"] and db.inserts == []
