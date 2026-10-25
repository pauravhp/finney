import {
  apiError,
  authenticated,
  json,
  rpcFailure,
  sameOrigin,
} from "@/lib/api";
import { commandSchema } from "@/lib/contracts";

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const body = commandSchema.parse(await request.json());
    const { supabase } = await authenticated();
    const { data, error } = await supabase.rpc("enqueue_finance_command", {
      p_organization_id: body.organization_id,
      p_run_id: body.run_id,
      p_command_type: body.command_type,
      p_payload: body.payload,
      p_idempotency_key: body.idempotency_key,
    });
    if (error) rpcFailure(error);
    return json({ job_id: data, status: "queued" }, 202);
  } catch (error) {
    return apiError(error);
  }
}
