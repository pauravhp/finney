"""Small launcher; the director's working interface is the browser dashboard."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from uuid import UUID

from app.config import Settings

ROOT = Path(__file__).resolve().parent.parent


def install_runtime_environment(settings: Settings) -> None:
    values = {
        "FINANCE_MODEL": settings.finance_model,
        "FINANCE_MODEL_BASE_URL": settings.finance_model_base_url,
        "FINANCE_MODEL_API_MODE": settings.finance_model_api_mode,
        "FINANCE_MODEL_API_KEY": settings.finance_model_api_key.get_secret_value(),
        "AI_GATEWAY_API_KEY": settings.ai_gateway_api_key.get_secret_value(),
        "FINANCE_HERMES_SOURCE": settings.finance_hermes_source,
        "FINANCE_HERMES_PYTHON": settings.finance_hermes_python,
    }
    for name, value in values.items():
        if value:
            os.environ[name] = value


async def doctor(settings: Settings, *, live: bool = False) -> dict:
    from app.setup_checks import doctor as check_setup

    return await check_setup(settings, live=live)


def migrate(settings: Settings) -> list[dict]:
    import psycopg

    url = settings.supabase_db_url.get_secret_value()
    if not url:
        raise RuntimeError("Configure SUPABASE_DB_URL for migrations")
    results = []
    with psycopg.connect(url, connect_timeout=15, sslmode="require", autocommit=True) as connection:
        # Serialize migration runners without locking unrelated application work.
        connection.execute("select pg_advisory_lock(716204812)")
        try:
            connection.execute("""create table if not exists public.finance_schema_migrations (
                name text primary key, sha256 text not null, applied_at timestamptz not null default now())""")
            connection.execute(
                "alter table public.finance_schema_migrations enable row level security"
            )
            connection.execute(
                "revoke all on public.finance_schema_migrations from public,anon,authenticated"
            )
            from app.resources import resource_path

            for file in sorted(resource_path("supabase/migrations").glob("*.sql")):
                content = file.read_text()
                checksum = hashlib.sha256(content.encode()).hexdigest()
                applied = connection.execute(
                    "select sha256 from public.finance_schema_migrations where name=%s",
                    (file.name,),
                ).fetchone()
                if applied:
                    if applied[0] != checksum:
                        raise RuntimeError("Applied migration changed; create a new migration")
                    results.append({"migration": file.name, "status": "already_applied"})
                    continue
                # The migration file supports SQL-editor use with BEGIN/COMMIT.
                # This runner owns the transaction so schema and receipt commit together.
                lines = content.splitlines()
                content = "\n".join(
                    line for line in lines if line.strip().lower() not in {"begin;", "commit;"}
                )
                with connection.transaction():
                    connection.execute(content, prepare=False)
                    connection.execute(
                        "insert into public.finance_schema_migrations(name,sha256) values(%s,%s)",
                        (file.name, checksum),
                    )
                results.append({"migration": file.name, "status": "applied"})
        finally:
            connection.execute("select pg_advisory_unlock(716204812)")
    return results


async def run_worker(
    settings: Settings, *, once: bool = False, auto_intake: bool | None = None
) -> None:
    from uuid import UUID

    from app.finance.jobs import JobQueue
    from app.finance.tools import FinanceToolClient
    from app.finance.types import Scope
    from app.scheduler import GmailIntakeScheduler
    from app.service import dispatch_job
    from app.storage.supabase import SupabaseClient, SupabaseError

    if not settings.configured()["supabase"]:
        raise RuntimeError("Supabase is required; run finance init")
    install_runtime_environment(settings)
    async with SupabaseClient(settings.supabase_url, settings.backend_key) as client:
        queue = JobQueue(client, settings.finance_worker_id)
        scheduler = (
            None
            if once
            else GmailIntakeScheduler(
                enabled=settings.finance_auto_intake_enabled
                if auto_intake is None
                else auto_intake,
                batch_size=settings.finance_auto_intake_batch_size,
            )
        )

        async def discover_due_mail() -> None:
            import httpx

            if scheduler is None:
                return
            try:
                # Keep discovery from delaying lease renewal during a long actor
                # call. Uncertain inserts recover by scope/minute idempotency.
                async with asyncio.timeout(20):
                    result = await scheduler.maybe_enqueue(client)
                if result and result["queued"]:
                    print(json.dumps({"scheduler": "gmail_intake", **result}))
            except SupabaseError as error:
                if error.status in {401, 403}:
                    raise
                print(
                    json.dumps(
                        {
                            "scheduler": "gmail_intake",
                            "status": "blocked",
                            "error_type": type(error).__name__,
                        }
                    )
                )
            except (httpx.HTTPError, TimeoutError):
                print(
                    json.dumps(
                        {
                            "scheduler": "gmail_intake",
                            "status": "blocked",
                            "reason": "discovery_unavailable_or_timed_out",
                        }
                    )
                )

        while True:
            await discover_due_mail()
            job = await queue.lease(lease_seconds=120)
            if not job:
                if once:
                    return
                await asyncio.sleep(
                    scheduler.delay(settings.finance_poll_seconds)
                    if scheduler
                    else settings.finance_poll_seconds
                )
                continue
            scope = Scope(
                UUID(job["organization_id"]),
                UUID(job["run_id"]),
                UUID(job["requested_by"]) if job.get("requested_by") else None,
            )
            tools = FinanceToolClient(scope, client)
            task = asyncio.create_task(dispatch_job(settings, job, tools, client))
            try:
                while not task.done():
                    await discover_due_mail()
                    done, _ = await asyncio.wait(
                        {task}, timeout=scheduler.delay(30) if scheduler else 30
                    )
                    if not done:
                        await queue.renew(job["id"], job["lease_token"], lease_seconds=120)
                result = await task
                retryable = result.get("retryable") is True
                if result.get("status") == "failed" or (
                    result.get("status") == "blocked" and retryable
                ):
                    await queue.fail(
                        job["id"],
                        job["lease_token"],
                        error_code=result.get("reason", "runtime_failed"),
                        retryable=retryable,
                    )
                else:
                    await queue.ack(job["id"], job["lease_token"], result)
                print(json.dumps({"job_id": job["id"], "status": result.get("status", "unknown")}))
            except Exception as exc:  # noqa: BLE001 -- safe launcher/job boundary never prints provider exception text
                task.cancel()
                await asyncio.gather(task, return_exceptions=True)
                if isinstance(exc, SupabaseError) and exc.status in {401, 403}:
                    raise RuntimeError("worker_authorization_failed_stop_without_retry") from None
                try:
                    code = f"Supabase:{exc.status}:{exc.code}" if isinstance(exc, SupabaseError) else type(exc).__name__
                    await queue.fail(job["id"], job["lease_token"], error_code=code)
                except SupabaseError as failure:
                    if failure.status in {401, 403}:
                        raise RuntimeError(
                            "worker_authorization_failed_stop_without_retry"
                        ) from None
                except Exception:  # noqa: BLE001, S110 -- a stale lease must never overwrite another worker
                    pass  # Lease may already belong to another worker; never overwrite it.
                print(
                    json.dumps(
                        {"job_id": job["id"], "status": "failed", "error_type": type(exc).__name__}
                    )
                )
            if once:
                return


def main() -> None:
    parser = argparse.ArgumentParser(description="Director Finance setup and persistent worker")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser("doctor", help="Check configuration without printing credentials")
    check.add_argument(
        "--live",
        action="store_true",
        help="Read-only REST/Gmail checks and small real model/Jev requests; no PostgreSQL login or intake",
    )
    sub.add_parser("migrate", help="Apply versioned migrations to the configured dedicated project")
    sub.add_parser(
        "migration-sql",
        help="Print the same receipt-tracked migrations for the owner SQL editor without connecting",
    )
    init = sub.add_parser("init", help="Resume agent-guided onboarding")
    init.add_argument(
        "--manual", action="store_true", help="Print verified next steps without inference"
    )
    worker = sub.add_parser("worker", help="Run the durable job worker")
    worker.add_argument("--once", action="store_true")
    worker.add_argument(
        "--no-auto-intake",
        action="store_true",
        help="Disable background Gmail discovery; process already-queued work only",
    )
    oauth = sub.add_parser(
        "oauth-server", help="Run the director's mailbox callback service without access logs"
    )
    oauth.add_argument("--host", default="127.0.0.1")
    oauth.add_argument("--port", type=int, default=8767)
    gmail = sub.add_parser("gmail-connect", help="Connect a director's Gmail through isolated Hermes")
    gmail.add_argument("--client-file", type=Path, help="Downloaded Google Desktop OAuth client JSON")
    gmail.add_argument("--import-token-file", type=Path, help="Explicit existing owner-private readonly Google token JSON")
    gmail.add_argument("--expected-mailbox", help="Mailbox address to verify before importing an existing grant")
    gmail.add_argument("--director-user-id", type=UUID, help="Existing shared-event director Auth UUID")
    gmail.add_argument("--complete", action="store_true", help="Securely prompt for the full Google redirect URL")
    coinbase = sub.add_parser("coinbase-connect", help="Connect an existing Coinbase Wallet to this private event")
    coinbase.add_argument("--director-user-id", type=UUID, help="Existing event director Auth UUID")
    coinbase.add_argument("--complete", action="store_true", help="Securely prompt for the full Coinbase loopback redirect")
    coinbase.add_argument("--inspect", action="store_true", help="Read connected wallet addresses without financial actions")
    event = sub.add_parser(
        "event-sql",
        help="Prepare restart-safe private event SQL for a confirmed director and optional approver",
    )
    event.add_argument("--name", required=True)
    event.add_argument("--director-user-id", required=True)
    event.add_argument("--approver-user-id", help="Optional distinct confirmed human's Auth UUID")
    event.add_argument("--currency", default="USD")
    event.add_argument("--plan-path", type=Path)
    ingest = sub.add_parser(
        "check-csv", help="Validate an opening snapshot/statement without saving it"
    )
    ingest.add_argument("path", type=Path)
    ingest.add_argument("--currency", required=True)
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.command == "doctor":
            result = asyncio.run(doctor(settings, live=args.live))
            print(json.dumps(result, indent=2))
            if not result["ready_for_worker"]:
                raise SystemExit(2)
        elif args.command == "migrate":
            print(json.dumps(migrate(settings), indent=2))
        elif args.command == "migration-sql":
            from app.setup_sql import migration_sql

            print(migration_sql())
        elif args.command == "init":
            from app.onboarding import onboard

            install_runtime_environment(settings)
            print(json.dumps(asyncio.run(onboard(settings, manual=args.manual)), indent=2))
        elif args.command == "worker":
            asyncio.run(
                run_worker(
                    settings, once=args.once, auto_intake=False if args.no_auto_intake else None
                )
            )
        elif args.command == "oauth-server":
            import uvicorn

            if not 1 <= args.port <= 65535:
                raise ValueError("OAuth server port is out of range")
            uvicorn.run(
                "app.connectors.oauth_api:create_app",
                factory=True,
                host=args.host,
                port=args.port,
                access_log=False,
                log_level="warning",
            )
        elif args.command == "gmail-connect":
            from app.connectors.hermes_gmail_auth import begin, finish, import_grant

            if args.complete:
                if args.client_file or args.director_user_id or args.import_token_file or args.expected_mailbox:
                    raise ValueError("Complete uses the stored authorization attempt")
                if not sys.stdin.isatty():
                    raise ValueError("Complete requires an interactive terminal for hidden input")
                import getpass

                callback = getpass.getpass("Paste the full Google localhost redirect URL (hidden): ")
                result = asyncio.run(finish(settings, callback))
            elif args.import_token_file:
                if args.client_file or not args.director_user_id or not args.expected_mailbox:
                    raise ValueError("Import requires director identity and expected mailbox, without a client file")
                result = asyncio.run(import_grant(settings, args.director_user_id, args.import_token_file,
                                                  expected_mailbox=args.expected_mailbox))
            else:
                if not args.client_file or not args.director_user_id or args.expected_mailbox:
                    raise ValueError("Start requires --client-file and --director-user-id")
                result = asyncio.run(begin(settings, args.director_user_id, args.client_file))
            print(json.dumps(result, indent=2))
        elif args.command == "coinbase-connect":
            from app.payments.authorization_connect import begin, finish

            if args.inspect:
                if args.complete or args.director_user_id:
                    raise ValueError("Inspect cannot start or complete authorization")
                from app.payments.authorization_connect import load_access_token
                from app.payments.wallet_mcp import CoinbaseWalletMCP

                async def inspect_wallet():
                    token = await load_access_token(settings)
                    if not token:
                        return {"status": "blocked", "reason": "coinbase_wallet_oauth_required"}
                    payload = await CoinbaseWalletMCP(token).call("get_wallets", {})
                    addresses = sorted(CoinbaseWalletMCP._wallet_addresses(payload))
                    return {"status": "observed", "wallet_addresses": addresses, "read_only": True,
                            "sender_selection": "one_verified_wallet" if len(addresses) == 1 else "ambiguous_or_missing", "payments_executed": False}

                result = asyncio.run(inspect_wallet())
            elif args.complete:
                if args.director_user_id or not sys.stdin.isatty():
                    raise ValueError("Complete requires an interactive hidden terminal prompt")
                import getpass

                callback = getpass.getpass("Paste the full Coinbase loopback redirect URL (hidden): ")
                result = asyncio.run(finish(settings, callback))
            else:
                if not args.director_user_id:
                    raise ValueError("An existing director Auth UUID is required")
                result = asyncio.run(begin(settings, args.director_user_id))
            print(json.dumps(result, indent=2))
        elif args.command == "event-sql":
            from app.event_setup import event_sql

            print(
                event_sql(
                    name=args.name,
                    director_user_id=args.director_user_id,
                    approver_user_id=args.approver_user_id,
                    currency=args.currency,
                    plan_path=args.plan_path or settings.finance_state_dir / "event-plan.json",
                )
            )
        elif args.command == "check-csv":
            from app.imports.csv_records import parse_finance_csv

            rows = parse_finance_csv(args.path.read_text(), currency=args.currency)
            print(
                json.dumps({"status": "validated", "record_count": len(rows), "persisted": False})
            )
    except KeyboardInterrupt:
        raise SystemExit(130)
    except Exception as exc:  # noqa: BLE001 -- safe launcher/job boundary never prints provider exception text
        # Do not print provider response bodies or database connection strings.
        from app.payments.authorization_connect import CoinbaseAuthorizationError
        details = {"reason": exc.code, "provider_status": exc.status, "provider_error": exc.provider_error} if isinstance(exc, CoinbaseAuthorizationError) else {}
        print(
            json.dumps(
                {
                    "status": "blocked",
                    "error_type": type(exc).__name__,
                    "next_step": "Run finance doctor and consult README troubleshooting",
                    **details,
                }
            ),
            file=sys.stderr,
        )
        raise SystemExit(1)


if __name__ == "__main__":
    main()
