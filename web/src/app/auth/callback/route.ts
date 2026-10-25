import { NextResponse } from "next/server";
import { serverSupabase } from "@/lib/supabase/server";
import { requestOrigin } from "@/lib/api";

export async function GET(request: Request) {
  const url = new URL(request.url);
  const origin = requestOrigin(request);
  const code = url.searchParams.get("code");
  const supabase = await serverSupabase();
  if (code && supabase) {
    const { error } = await supabase.auth.exchangeCodeForSession(code);
    if (!error)
      return NextResponse.redirect(new URL("/", origin), {
        headers: { "Cache-Control": "private, no-store" },
      });
  }
  return NextResponse.redirect(new URL("/?auth_error=1", origin), {
    headers: { "Cache-Control": "private, no-store" },
  });
}
