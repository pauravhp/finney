"""Local transport fixtures for the actor/service boundary; no hosted requests."""

import unittest
from unittest.mock import AsyncMock, patch
from uuid import UUID

import httpx

from app.config import Settings
from app.finance.tools import FinanceToolClient
from app.finance.types import FinanceError, Scope
from app.service import IntegratedTools, dispatch_job
from app.storage.supabase import SupabaseClient


class IntegratedServiceBoundary(unittest.IsolatedAsyncioTestCase):
    async def test_dispatch_forwards_same_settings_to_actor_and_tool_wrapper(self):
        def deny_network(request):
            raise AssertionError("Unit dispatch must not access any provider")

        supplied = Settings(_env_file=None, finance_model_api_key="unit-placeholder")
        async with SupabaseClient(
            "https://unit.invalid", "unit-placeholder", transport=httpx.MockTransport(deny_network)
        ) as db:
            finance = FinanceToolClient(Scope(UUID(int=1), UUID(int=2)), db)
            job = {"id": "unit-job", "command_type": "evaluate_improvement", "payload": {}}
            fake = AsyncMock(return_value={"status": "blocked", "reason": "unit-fixture"})
            with patch("app.runtime.jobs.run_job", fake):
                await dispatch_job(supplied, job, finance, db)
            self.assertIs(fake.await_args.kwargs["settings"], supplied)
            self.assertIs(fake.await_args.args[1].settings, supplied)

    async def test_evaluation_keeps_scope_without_live_intake_or_database_reads(self):
        def deny_network(request):
            raise AssertionError("Snapshot reads must not access the live transport")

        async with SupabaseClient(
            "https://unit.invalid", "unit-placeholder", transport=httpx.MockTransport(deny_network)
        ) as db:
            scope = Scope(UUID(int=1), UUID(int=2), UUID(int=3))
            integrated = IntegratedTools(FinanceToolClient(scope, db), db)
            snapshot = {
                "organization": {"id": str(scope.organization_id)},
                "run": {"id": str(scope.run_id)},
                "cases": [{"id": "unit-case", "status": "open"}],
                "obligations": [],
            }
            scoped = integrated.for_evaluation(snapshot)
            self.assertEqual(integrated.scope, scope)
            self.assertTrue(scoped.prepare_only)
            self.assertIsInstance(scoped, FinanceToolClient)
            self.assertEqual(
                (await scoped.call("get_case", {"case_id": "unit-case"}))["id"], "unit-case"
            )
            with self.assertRaises(FinanceError):
                await scoped.call("search_finance_mail", {"query": "anything"})
            with self.assertRaises(FinanceError):
                await scoped.call("confirm_payment", {})

    async def test_mail_search_is_imported_run_scoped_and_rejects_model_scope(self):
        seen = []

        def handler(request):
            seen.append(request)
            return httpx.Response(200, json=[])

        async with SupabaseClient(
            "https://unit.invalid", "unit-placeholder", transport=httpx.MockTransport(handler)
        ) as db:
            scope = Scope(UUID(int=1), UUID(int=2))
            integrated = IntegratedTools(FinanceToolClient(scope, db), db)
            result = await integrated.call("search_finance_mail", {"query": "receipt"})
            self.assertEqual(result["scope"], "imported_finance_evidence")
            self.assertEqual(len(seen), 1)
            query = seen[0].url.params
            self.assertEqual(query["organization_id"], "eq." + str(scope.organization_id))
            self.assertEqual(query["run_id"], "eq." + str(scope.run_id))
            self.assertEqual(query["source_type"], "eq.gmail")
            with self.assertRaises(FinanceError):
                await integrated.call("search_finance_mail", {"organization_id": str(UUID(int=9))})
            self.assertEqual(len(seen), 1)

    async def test_autonomous_proposal_preserves_separate_human_approval_identity(self):
        submitted = []

        def handler(request):
            import json

            submitted.append(json.loads(request.content))
            if submitted[-1]["p_operation"] == "assert_payment_run_authorized":
                return httpx.Response(200, json={"authorized": True, "is_demo": False, "organization_id": str(UUID(int=1)), "run_id": str(UUID(int=2)), "sender": "0x" + "1" * 40})
            return httpx.Response(200, json={"id": str(UUID(int=8))})

        settings = Settings(_env_file=None, coinbase_sender_address="0x" + "1" * 40, organization_id=UUID(int=1), run_id=UUID(int=2))
        async with SupabaseClient(
            "https://unit.invalid", "unit-placeholder", transport=httpx.MockTransport(handler)
        ) as db:
            scope = Scope(UUID(int=1), UUID(int=2), UUID(int=3))
            integrated = IntegratedTools(FinanceToolClient(scope, db), db)
            with patch("app.service.Settings", return_value=settings):
                await integrated.call(
                    "create_approval_request",
                    {
                        "action": {
                            "type": "payment",
                            "amount_minor": 8700,
                            "currency": "USD",
                            "asset": "USDC",
                            "network": "eip155:84532",
                            "destination": "0x" + "2" * 40,
                            "obligation_id": str(UUID(int=4)),
                            "obligation_version": 1,
                        },
                        "idempotency_key": "unit-proposal",
                    },
                )
            self.assertEqual(submitted[1]["p_operation"], "create_approval_request")
            self.assertIsNone(submitted[1]["p_arguments"]["proposed_by"])
            self.assertEqual(integrated.scope.actor_id, UUID(int=3))


if __name__ == "__main__":
    unittest.main()
