type AuthFailure = { code?: string; status?: number } | null;

export function authErrorMessage(error: AuthFailure): string {
  switch (error?.code) {
    case "invalid_credentials":
      return "The email or password was not accepted. Check both and try again.";
    case "email_not_confirmed":
      return "Confirm your email before signing in. Open the confirmation link in the browser where you created your account. If no email arrived, ask the event owner to check email delivery.";
    case "signup_disabled":
      return "Email account creation is unavailable. Ask the event owner to create your account or enable email sign-up.";
    case "email_provider_disabled":
      return "Email sign-in is unavailable. Ask the event owner to enable it in Supabase Auth.";
    case "email_address_invalid":
    case "validation_failed":
      return "Check your email address and password, then try again.";
    case "weak_password":
      return "Choose a stronger password with more characters and a mix of letters, numbers, and symbols.";
    case "over_email_send_rate_limit":
    case "over_request_rate_limit":
      return "Too many attempts. Wait a few minutes before trying again. If a confirmation email does not arrive, ask the event owner to check email delivery.";
    case "email_address_not_authorized":
      return "Confirmation email cannot be sent to this address with the current email setup. Ask the event owner to check email delivery or create your account.";
    case "user_banned":
      return "This account cannot sign in. Ask the event owner to check your account access.";
    default:
      return error?.status === 429
        ? "Too many attempts. Wait a few minutes before trying again."
        : "Account access could not finish. Check your connection and try again. If it continues, ask the event owner to check Supabase Auth and email delivery.";
  }
}
// Preserve an event deep link through sign-in without accepting a redirect URL.
export function financeReturnPath(search: string): string {
  const input = new URLSearchParams(search);
  const scoped = new URLSearchParams();
  for (const key of ["organization_id", "run_id"]) {
    const value = input.get(key);
    if (
      value &&
      /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(
        value,
      )
    )
      scoped.set(key, value);
  }
  return scoped.size === 2 ? `/desk?${scoped}` : "/desk";
}
