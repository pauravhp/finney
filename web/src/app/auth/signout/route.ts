import { apiError, json, sameOrigin } from "@/lib/api";
import { serverSupabase } from "@/lib/supabase/server";

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const supabase = await serverSupabase();
    if (supabase) await supabase.auth.signOut();
    return json({ signed_out: true });
  } catch (error) {
    return apiError(error);
  }
}
