import { apiError, authenticated, json, rpcFailure } from "@/lib/api";
import type { ScopeChoice } from "@/lib/contracts";

export async function GET() {
  try {
    const { supabase, user } = await authenticated();
    const memberships = await supabase
      .from("memberships")
      .select("organization_id,role")
      .eq("user_id", user.id)
      .eq("active", true);
    if (memberships.error) rpcFailure(memberships.error);
    const ids = memberships.data.map((row) => row.organization_id as string);
    if (!ids.length) return json({ scopes: [] });
    const [organizations, runs] = await Promise.all([
      supabase.from("organizations").select("id,name").in("id", ids),
      supabase
        .from("demo_runs")
        .select("id,organization_id,name,status,is_demo")
        .in("organization_id", ids)
        .order("created_at", { ascending: false }),
    ]);
    if (organizations.error) rpcFailure(organizations.error);
    if (runs.error) rpcFailure(runs.error);
    const scopes: ScopeChoice[] = organizations.data.map((org) => ({
      organization_id: org.id,
      organization_name: org.name,
      role:
        memberships.data.find((row) => row.organization_id === org.id)?.role ??
        "viewer",
      runs: runs.data
        .filter((run) => run.organization_id === org.id)
        .map(({ id, name, status, is_demo }) => ({
          id,
          name,
          status,
          is_demo,
        })),
    }));
    return json({ scopes });
  } catch (error) {
    return apiError(error);
  }
}
