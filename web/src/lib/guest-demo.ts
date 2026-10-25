import { financeReturnPath } from "@/lib/auth";
import { scopeSchema } from "@/lib/contracts";

type GuestIdentity = { is_anonymous?: boolean };
type GuestSession = {
  access_token: string;
  user: GuestIdentity;
};
type AuthFailure = { code?: string; status?: number } | null;

type GuestAuthClient = {
  getSession(): Promise<{
    data: { session: GuestSession | null };
    error: AuthFailure;
  }>;
  signInAnonymously(): Promise<{
    data: { session: GuestSession | null; user: GuestIdentity | null };
    error: AuthFailure;
  }>;
};

type GuestDemoErrorCode =
  | "disabled"
  | "account_session_active"
  | "anonymous_provider_disabled"
  | "signup_disabled"
  | "captcha_required"
  | "rate_limited"
  | "not_anonymous"
  | "auth_failed"
  | "network_failed"
  | "request_uncertain"
  | "session_rejected"
  | "demo_forbidden"
  | "service_unavailable"
  | "invalid_response"
  | "invalid_scope";

export class GuestDemoError extends Error {
  constructor(readonly code: GuestDemoErrorCode) {
    super(code);
    this.name = "GuestDemoError";
  }
}

export function guestDemoEntryEnabled(value: string | undefined): boolean {
  return value === "true";
}

export function guestDemoReturnPath(value: unknown): string {
  const scope = scopeSchema.safeParse(value);
  if (!scope.success) throw new GuestDemoError("invalid_scope");
  const query = new URLSearchParams({
    organization_id: scope.data.organization_id,
    run_id: scope.data.run_id,
  });
  return financeReturnPath(`?${query.toString()}`);
}

export function guestDemoErrorMessage(error: unknown): string {
  if (error instanceof GuestDemoError) {
    switch (error.code) {
      case "disabled":
        return "Guest demos are not enabled in this build. Ask the event owner to enable guest access.";
      case "account_session_active":
        return "A regular account is already signed in in this browser. Sign out before opening an isolated guest demo.";
      case "anonymous_provider_disabled":
        return "Guest sign-in is disabled in this Supabase project. Ask the event owner to enable anonymous sign-ins.";
      case "signup_disabled":
        return "Supabase is not accepting new guest identities. Ask the event owner to review the sign-up policy and anonymous sign-in settings.";
      case "captcha_required":
        return "Supabase requires CAPTCHA for guest sign-in. The event owner must finish the configured CAPTCHA flow before guest access can open.";
      case "rate_limited":
        return "Guest sign-in is rate limited. Wait a few minutes and try again.";
      case "not_anonymous":
        return "Supabase did not return a guest identity, so the demo was stopped. Try a private browser window or ask the event owner to check Auth setup.";
      case "session_rejected":
        return "Guest sign-in completed, but the finance app could not verify that session. Refresh and try again; ask the event owner to check Auth cookie and site URL settings if it continues.";
      case "demo_forbidden":
        return "Guest sign-in worked, but this project cannot create an isolated demo. Ask the event owner to check demo access and database migrations.";
      case "service_unavailable":
        return "The finance service could not create the isolated demo. Ask the event owner to check the database and worker setup.";
      case "network_failed":
        return "Guest access could not reach Supabase or the finance app. Check your connection and try again.";
      case "request_uncertain":
        return "The finance app stopped responding while opening the demo, so its creation status is unknown. Refresh to check your workspace before starting another demo.";
      case "invalid_scope":
      case "invalid_response":
        return "The finance app returned an invalid demo response. Refresh and ask the event owner to check the service.";
      case "auth_failed":
        return "Guest sign-in could not finish. Check the connection and ask the event owner to check Supabase Auth setup.";
    }
  }

  return "Guest access could not finish. Check your connection and try again. If it continues, ask the event owner to check Supabase Auth and demo setup.";
}

function authFailure(error: AuthFailure): GuestDemoError {
  if (error?.code === "anonymous_provider_disabled")
    return new GuestDemoError("anonymous_provider_disabled");
  if (error?.code === "signup_disabled")
    return new GuestDemoError("signup_disabled");
  if (error?.code === "captcha_failed" || error?.code === "captcha_not_enabled")
    return new GuestDemoError("captcha_required");
  if (error?.code === "over_request_rate_limit" || error?.status === 429)
    return new GuestDemoError("rate_limited");
  if (error?.code === "request_timeout")
    return new GuestDemoError("network_failed");
  return new GuestDemoError("auth_failed");
}

function responseFailure(status: number): GuestDemoError {
  if (status === 401) return new GuestDemoError("session_rejected");
  if (status === 403) return new GuestDemoError("demo_forbidden");
  if (status === 429) return new GuestDemoError("rate_limited");
  if (status >= 500) return new GuestDemoError("service_unavailable");
  return new GuestDemoError("invalid_response");
}

type GuestDemoResponse = {
  ok: boolean;
  status: number;
  json(): Promise<unknown>;
};

export async function createGuestDemo(options: {
  enabled: boolean;
  auth: GuestAuthClient;
  fetcher?: (input: string, init: RequestInit) => Promise<GuestDemoResponse>;
}): Promise<string> {
  if (!options.enabled) throw new GuestDemoError("disabled");

  let session: GuestSession | null;
  try {
    const current = await options.auth.getSession();
    if (current.error) throw authFailure(current.error);
    session = current.data.session;
  } catch (error) {
    if (error instanceof GuestDemoError) throw error;
    throw new GuestDemoError("network_failed");
  }

  if (session && session.user.is_anonymous !== true)
    throw new GuestDemoError("account_session_active");

  if (!session) {
    try {
      const result = await options.auth.signInAnonymously();
      if (result.error) throw authFailure(result.error);
      session = result.data.session;
      if (result.data.user?.is_anonymous !== true)
        throw new GuestDemoError("not_anonymous");
    } catch (error) {
      if (error instanceof GuestDemoError) throw error;
      throw new GuestDemoError("network_failed");
    }
  }

  // Fail closed if Auth ever returns a normal account or an incomplete session.
  if (!session || !session.access_token || session.user.is_anonymous !== true)
    throw new GuestDemoError("not_anonymous");

  let response: GuestDemoResponse;
  try {
    const fetcher = options.fetcher ?? fetch;
    response = await fetcher("/api/finance/demo", {
      method: "POST",
      credentials: "same-origin",
      cache: "no-store",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: "Guest finance demo" }),
    });
  } catch {
    throw new GuestDemoError("request_uncertain");
  }

  if (!response.ok) throw responseFailure(response.status);

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new GuestDemoError("invalid_response");
  }
  return guestDemoReturnPath(body);
}
