import { ApiError, apiError, authenticated, json, rpcFailure } from "@/lib/api";
import {
  assertSnapshotScope,
  scopeSchema,
  snapshotSchema,
} from "@/lib/contracts";

export async function GET(request: Request) {
  try {
    const scope = scopeSchema.parse(
      Object.fromEntries(new URL(request.url).searchParams),
    );
    const { supabase } = await authenticated();
    const { data, error } = await supabase.rpc("get_finance_snapshot", {
      p_organization_id: scope.organization_id,
      p_run_id: scope.run_id,
    });
    if (error) rpcFailure(error);
    const parsed = snapshotSchema.safeParse(data);
    if (!parsed.success)
      throw new ApiError(
        502,
        "The finance snapshot is incompatible. Check the database migration version.",
      );
    return json(assertSnapshotScope(parsed.data, scope));
  } catch (error) {
    return apiError(error);
  }
}
