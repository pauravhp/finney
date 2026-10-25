import {
  ApiError,
  apiError,
  authenticated,
  json,
  rpcFailure,
  sameOrigin,
} from "@/lib/api";
import {
  approvalPolicyResultSchema,
  approvalPolicySchema,
  snapshotSchema,
} from "@/lib/contracts";

// The route passes the normal cookie-authenticated client. Tests inject only
// explicit local fixtures; no service role or caller-supplied identity is used.
export async function updateApprovalPolicy(
  request: Request,
  authenticate: typeof authenticated,
) {
  try {
    sameOrigin(request);
    const body = approvalPolicySchema.parse(await request.json());
    const { supabase, user } = await authenticate();
    const membership = await supabase
      .from("memberships")
      .select("role")
      .eq("organization_id", body.organization_id)
      .eq("user_id", user.id)
      .eq("active", true)
      .maybeSingle();
    if (membership.error) rpcFailure(membership.error);
    if (membership.data?.role !== "director")
      throw new ApiError(
        403,
        "Only the event director can change payment approvals.",
      );
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
    if (
      parsed.data.organization.id !== body.organization_id ||
      parsed.data.run.id !== body.run_id
    )
      throw new ApiError(
        403,
        "This financial state does not belong to the selected run.",
      );
    if (parsed.data.run.revision !== body.expected_revision)
      throw new ApiError(
        409,
        "This run has changed. Refresh and review the current approval policy before saving.",
      );
    const { data, error } = await supabase.rpc("set_event_approval_policy", {
      p_organization_id: body.organization_id,
      p_run_id: body.run_id,
      p_required_approvals: body.required_approvals,
      p_expected_revision: body.expected_revision,
    });
    if (error?.code === "40001")
      throw new ApiError(
        409,
        "This run changed while saving. Refresh and review the current approval policy before trying again.",
      );
    if (
      error?.code === "23514" &&
      error.message === "unsettled payments prevent approval policy change"
    )
      throw new ApiError(
        409,
        "The approval policy cannot change while a payment is in flight or awaiting settlement review. Resolve that payment, then refresh and try again.",
      );
    if (error) rpcFailure(error);
    const result = approvalPolicyResultSchema.safeParse(data);
    if (
      !result.success ||
      result.data.organization_id !== body.organization_id ||
      result.data.run_id !== body.run_id ||
      result.data.required_payment_approvals !== body.required_approvals
    )
      throw new ApiError(
        502,
        "The finance service returned an incompatible approval policy. Refresh to check the saved state.",
      );
    return json(result.data);
  } catch (error) {
    return apiError(error);
  }
}
