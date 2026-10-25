"""Create/resume and enqueue a guided scenario as an authenticated owner.

Use an existing short-lived owner access token in FINANCE_GUIDED_OWNER_ACCESS_TOKEN;
never a service key. No secrets are printed. The existing worker does the seed.
"""

import asyncio
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.config import Settings
from app.storage.supabase import SupabaseClient


async def main():
    settings = Settings()
    token = os.environ.get("FINANCE_GUIDED_OWNER_ACCESS_TOKEN")
    if not token:
        raise SystemExit(
            "FINANCE_GUIDED_OWNER_ACCESS_TOKEN required from the protected owner session"
        )
    async with SupabaseClient(
        settings.supabase_url, settings.supabase_publishable_key, access_token=token
    ) as owner:
        result = await owner.rpc("create_finance_guided_demo", {})
    print(
        json.dumps(
            {
                key: result[key]
                for key in ("organization_id", "run_id", "seed_job_id", "seed_status")
            }
        )
    )


if __name__ == "__main__":
    asyncio.run(main())
