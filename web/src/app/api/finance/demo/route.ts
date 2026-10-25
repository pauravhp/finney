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
    demoSchema.parse(await request.json());
    const { supabase } = await authenticated();
    const { data, error } = await supabase.rpc("create_finance_guided_demo");
    if (error) rpcFailure(error);
    const scope = scopeSchema.parse(data);
    return json(
      {
        ...scope,
        seed_status: data.seed_status,
        seed_job_id: data.seed_job_id ?? null,
      },
      201,
    );
  } catch (error) {
    return apiError(error);
  }
}
