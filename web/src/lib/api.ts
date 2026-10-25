import { NextResponse } from "next/server";
import { z } from "zod";
import { serverSupabase } from "@/lib/supabase/server";

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

export async function authenticated() {
  const supabase = await serverSupabase();
  if (!supabase)
    throw new ApiError(
      503,
      "Supabase is not configured. Add the public URL and publishable key to the web environment.",
    );
  // getUser verifies the session with Auth; cookie contents never authorize the request alone.
  const { data, error } = await supabase.auth.getUser();
  if (error || !data.user)
    throw new ApiError(401, "Your session has expired. Sign in to continue.");
  return { supabase, user: data.user };
}

export function requestOrigin(request: Request) {
  const url = new URL(request.url);
  // Next's local server can normalize request.url to localhost while preserving Host.
  // Use the actual HTTP authority; never trust a caller's forwarded-host override.
  url.host = request.headers.get("host") ?? url.host;
  return url.origin;
}

export function sameOrigin(request: Request) {
  if (request.headers.get("origin") !== requestOrigin(request))
    throw new ApiError(403, "The request must come from this application.");
  if (!request.headers.get("content-type")?.includes("application/json"))
    throw new ApiError(415, "Send application/json.");
}

export function rpcFailure(error: { code?: string; message?: string }): never {
  const code = error.code ?? "";
  if (["22023", "22003", "22P02"].includes(code))
    throw new ApiError(
      400,
      "The request is invalid or conflicts with the current financial state. Check the amount, evidence and allocation.",
    );
  if (["42501", "PGRST301"].includes(code))
    throw new ApiError(403, "You do not have access to this run or action.");
  if (["40001", "23505", "P0001"].includes(code))
    throw new ApiError(
      409,
      "This action could not be accepted. Refresh and check its current version, approvals, and eligibility.",
    );
  if (["42883", "PGRST202", "42P01"].includes(code))
    throw new ApiError(
      503,
      "The finance database is not ready. Apply the supplied migrations and reload.",
    );
  throw new ApiError(
    502,
    "The finance service could not complete this request. Retry after checking connection health.",
  );
}

export function json(data: unknown, status = 200) {
  return NextResponse.json(data, {
    status,
    headers: { "Cache-Control": "private, no-store" },
  });
}
export function apiError(error: unknown) {
  if (error instanceof ApiError)
    return json({ error: error.message }, error.status);
  if (error instanceof z.ZodError || error instanceof SyntaxError)
    return json(
      { error: "The request contains invalid or missing fields." },
      400,
    );
  return json(
    {
      error:
        "The service returned an unexpected result. Refresh or check the server configuration.",
    },
    502,
  );
}
