import { z } from "zod";
import {
  apiError,
  authenticated,
  json,
  rpcFailure,
  sameOrigin,
} from "@/lib/api";
import { scopeSchema, uuid } from "@/lib/contracts";

const proposal = scopeSchema
  .extend({
    operation: z.literal("propose"),
    arguments: z
      .object({
        budget_line_id: uuid.optional(),
        expected_version: z.number().int().positive().optional(),
        new_name: z.string().trim().min(1).max(120).optional(),
        allocated_minor: z.string().regex(/^\d+$/),
        rationale: z.string().trim().min(1).max(2000),
        idempotency_key: z.string().min(8).max(200),
      })
      .strict(),
  })
  .strict();
const decision = scopeSchema
  .extend({
    operation: z.literal("decide"),
    decision_id: uuid,
    decision: z.enum(["approve", "reject"]),
  })
  .strict();

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const body = z
      .discriminatedUnion("operation", [proposal, decision])
      .parse(await request.json());
    const { supabase } = await authenticated();
    const scope = {
      p_organization_id: body.organization_id,
      p_run_id: body.run_id,
    };
    const { data, error } =
      body.operation === "propose"
        ? await supabase.rpc("propose_finance_budget", {
            ...scope,
            p_arguments: body.arguments,
          })
        : await supabase.rpc("decide_finance_budget", {
            ...scope,
            p_decision_id: body.decision_id,
            p_decision: body.decision,
          });
    if (error) rpcFailure(error);
    return json(data);
  } catch (error) {
    return apiError(error);
  }
}
