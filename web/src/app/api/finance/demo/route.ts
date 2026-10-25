import {
  apiError,
  authenticated,
  json,
  rpcFailure,
  sameOrigin,
} from "@/lib/api";
import { demoSchema, scopeSchema } from "@/lib/contracts";

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const body = demoSchema.parse(await request.json());
    const { supabase } = await authenticated();
    const { data, error } = await supabase.rpc("create_finance_demo", {
      p_name: body.name,
      p_previous_run_id: body.previous_run_id,
    });
    if (error) rpcFailure(error);
    const scope = scopeSchema.parse(data);
    const seeded = await supabase.rpc("enqueue_finance_command", {
      p_organization_id: scope.organization_id,
      p_run_id: scope.run_id,
      p_command_type: "intake",
      p_payload: { source: "demo_bundle" },
      p_idempotency_key: `demo-seed:${scope.run_id}`,
    });
    return json(
      {
        ...scope,
        seed_status: seeded.error ? "blocked" : "queued",
        seed_job_id: seeded.data ?? null,
      },
      201,
    );
  } catch (error) {
    return apiError(error);
  }
}
