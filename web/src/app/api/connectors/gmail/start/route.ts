import { ApiError, apiError, authenticated, json, sameOrigin } from "@/lib/api";
import { scopeSchema } from "@/lib/contracts";
import { financeApiUrl, googleAuthorizationUrl } from "@/lib/connectors";

export async function POST(request: Request) {
  try {
    sameOrigin(request);
    const scope = scopeSchema.strict().parse(await request.json());
    const { supabase } = await authenticated();
    const base = financeApiUrl();
    if (!base)
      throw new ApiError(
        503,
        "Ask the event owner to connect Gmail through Hermes using finance gmail-connect on the worker host.",
      );
    const { data } = await supabase.auth.getSession();
    if (!data.session?.access_token)
      throw new ApiError(
        401,
        "Sign in again before connecting the event mailbox.",
      );
    const result = await fetch(new URL("/oauth/gmail/start", base), {
      method: "POST",
      cache: "no-store",
      signal: AbortSignal.timeout(15000),
      redirect: "error",
      headers: {
        "Content-Type": "application/json",
        Authorization: `Bearer ${data.session.access_token}`,
      },
      body: JSON.stringify(scope),
    });
    if (!result.ok) {
      if (result.status === 409)
        throw new ApiError(
          409,
          "This event uses Hermes for Gmail. The event owner connects it once with finance gmail-connect on the worker host.",
        );
      if (result.status === 403)
        throw new ApiError(
          403,
          "Only an event director can connect Gmail for a shared event run. Personal demo runs do not connect a mailbox.",
        );
      if (result.status === 401)
        throw new ApiError(
          401,
          "Your mailbox connection session expired. Sign in again.",
        );
      throw new ApiError(
        503,
        "Gmail authorization is not ready. Check the event's Google OAuth and mailbox service configuration.",
      );
    }
    const response: unknown = await result.json();
    const url = googleAuthorizationUrl(
      response && typeof response === "object"
        ? (response as Record<string, unknown>).authorization_url
        : null,
    );
    if (!url)
      throw new ApiError(
        502,
        "The mailbox service returned an invalid authorization destination.",
      );
    // OAuth state stays ephemeral: return to this director only, no audit payload or log.
    return json({ authorization_url: url });
  } catch (error) {
    return apiError(error);
  }
}
