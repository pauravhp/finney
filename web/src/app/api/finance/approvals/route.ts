import {
  ApiError,
  apiError,
  authenticated,
  json,
  rpcFailure,
  sameOrigin,
} from "@/lib/api";
import { approvalSchema, snapshotSchema } from "@/lib/contracts";

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const body = approvalSchema.parse(await request.json());
    const { supabase } = await authenticated();
    const snapshot = await supabase.rpc("get_finance_snapshot", {
      p_organization_id: body.organization_id,
      p_run_id: body.run_id,
    });
    if (snapshot.error) rpcFailure(snapshot.error);
    const parsed = snapshotSchema.safeParse(snapshot.data);
    if (!parsed.success)
      throw new ApiError(
        502,
        "The finance snapshot is incompatible. Check the database migration version.",
      );
    const proposal = parsed.data.approvals.find(
      (row) => row.id === body.proposal_id,
    );
    if (!proposal)
      throw new ApiError(
        403,
        "This proposal does not belong to the selected run.",
      );
    if (proposal.action_hash !== body.expected_action_hash)
      throw new ApiError(
        409,
        "This proposal has changed. Review its new action before deciding.",
      );
    const { data, error } = await supabase.rpc("approve_finance_proposal", {
      p_proposal_id: body.proposal_id,
      p_expected_action_hash: body.expected_action_hash,
      p_decision: body.decision,
    });
    if (error) rpcFailure(error);
    return json(data);
  } catch (error) {
    return apiError(error);
  }
}
