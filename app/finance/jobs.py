from __future__ import annotations

from typing import Any
from uuid import UUID

from app.storage.supabase import SupabaseClient


class JobQueue:
    def __init__(self, client: SupabaseClient, worker_id: str):
        if not worker_id or len(worker_id) > 128:
            raise ValueError("worker id required")
        self.client, self.worker_id = client, worker_id

    async def lease(self, *, lease_seconds: int = 120) -> dict[str, Any] | None:
        return await self.client.rpc("lease_finance_job", {"p_worker_id": self.worker_id, "p_lease_seconds": lease_seconds})

    async def ack(self, job_id: UUID | str, lease_token: UUID | str, result: dict[str, Any]) -> None:
        await self.client.rpc("finish_finance_job", {"p_job_id": str(job_id), "p_lease_token": str(lease_token), "p_result": result})

    async def renew(self, job_id: UUID | str, lease_token: UUID | str, *, lease_seconds: int = 120) -> None:
        await self.client.rpc("renew_finance_job", {"p_job_id": str(job_id), "p_lease_token": str(lease_token), "p_lease_seconds": lease_seconds})

    async def fail(self, job_id: UUID | str, lease_token: UUID | str, *, error_code: str, retryable: bool = False) -> None:
        await self.client.rpc("fail_finance_job", {"p_job_id": str(job_id), "p_lease_token": str(lease_token),
                                                  "p_error_code": error_code, "p_retryable": retryable})

    async def heartbeat(self) -> None:
        await self.client.rpc("finance_worker_heartbeat", {"p_worker_id": self.worker_id})
