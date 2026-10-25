"use client";

import { useState, type FormEvent } from "react";
import {
  ArrowRight,
  Check,
  CircleHelp,
  LoaderCircle,
  ShieldCheck,
} from "lucide-react";
import { authErrorMessage, financeReturnPath } from "@/lib/auth";
import {
  createGuestDemo,
  guestDemoEntryEnabled,
  guestDemoErrorMessage,
} from "@/lib/guest-demo";
import { browserSupabase } from "@/lib/supabase/browser";

export function AuthPanel({ callbackError }: { callbackError: boolean }) {
  const guestDemoEnabled = guestDemoEntryEnabled(
    process.env.NEXT_PUBLIC_FINANCE_GUEST_DEMO,
  );
  const [mode, setMode] = useState<"signin" | "signup">("signin");
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [busyAction, setBusyAction] = useState<"account" | "guest" | null>(
    null,
  );
  const busy = busyAction !== null;
  const [pending, setPending] = useState(false);
  const [guestError, setGuestError] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(
    callbackError
      ? "The confirmation link could not finish. It may have expired or been opened in another browser. Try signing in if you already confirmed your email; otherwise ask the event owner to check your account."
      : null,
  );

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (busy) return;
    setBusyAction("account");
    setError(null);
    try {
      const client = browserSupabase();
      const credentials = { email: email.trim(), password };
      const { data, error: authError } =
        mode === "signup"
          ? await client.auth.signUp({
              ...credentials,
              options: {
                emailRedirectTo: `${window.location.origin}/auth/callback`,
              },
            })
          : await client.auth.signInWithPassword(credentials);
      setPassword("");
      if (authError) {
        setError(authErrorMessage(authError));
      } else if (data.session) {
        window.location.replace(financeReturnPath(window.location.search));
      } else if (mode === "signup") {
        setPending(true);
      } else {
        setError(
          "No sign-in session was created. Try again or ask the event owner to check your account.",
        );
      }
    } catch {
      setPassword("");
      setError(authErrorMessage(null));
    } finally {
      setBusyAction(null);
    }
  }

  async function startGuestDemo() {
    if (busy || !guestDemoEnabled) return;
    setBusyAction("guest");
    setError(null);
    setGuestError(null);
    try {
      const client = browserSupabase();
      const destination = await createGuestDemo({
        enabled: guestDemoEnabled,
        auth: client.auth,
      });
      window.location.replace(destination);
    } catch (caught) {
      setGuestError(guestDemoErrorMessage(caught));
    } finally {
      setBusyAction(null);
    }
  }

  function changeMode(next: "signin" | "signup") {
    setMode(next);
    setPassword("");
    setError(null);
    setGuestError(null);
    setPending(false);
  }

  return (
    <section className="signin-panel" aria-labelledby="auth-heading">
      <span className="setup-symbol">
        <ShieldCheck size={29} aria-hidden="true" />
      </span>
      <div className="auth-content">
        <h2 id="auth-heading">
          {pending
            ? "Check your email to continue"
            : mode === "signup"
              ? "Create your finance account"
              : "Your event. Your team's decisions."}
        </h2>
        {pending ? (
          <>
            <div className="auth-confirmation" role="status">
              <Check size={19} aria-hidden="true" />
              <p>
                If this address can be registered, use the confirmation link to
                finish creating your account. Open it in this browser to
                continue.
              </p>
            </div>
            <p>
              If no email arrives, check spam or ask the event owner to check
              email delivery or create your account.
            </p>
            <button className="primary" onClick={() => changeMode("signin")}>
              Back to sign in <ArrowRight size={16} aria-hidden="true" />
            </button>
          </>
        ) : (
          <>
            <p>
              {mode === "signup"
                ? "Use your email and a password. Confirm your email before opening your workspace."
                : "Sign in with your email and password to open your team's finance runs."}
            </p>
            <form
              className="auth-form"
              method="post"
              onSubmit={submit}
              aria-busy={busyAction === "account"}
            >
              <label htmlFor="auth-email">Email address</label>
              <input
                id="auth-email"
                name="email"
                type="email"
                autoComplete="email"
                autoCapitalize="none"
                spellCheck={false}
                value={email}
                onChange={(event) => setEmail(event.target.value)}
                disabled={busy}
                required
              />
              <label htmlFor="auth-password">Password</label>
              <input
                id="auth-password"
                name="password"
                type="password"
                autoComplete={
                  mode === "signup" ? "new-password" : "current-password"
                }
                value={password}
                onChange={(event) => setPassword(event.target.value)}
                minLength={mode === "signup" ? 8 : undefined}
                aria-describedby={
                  mode === "signup" ? "password-help" : undefined
                }
                disabled={busy}
                required
              />
              {mode === "signup" && (
                <small id="password-help">
                  Use at least 8 characters. Your event may require a stronger
                  password.
                </small>
              )}
              {error && (
                <div className="auth-error" role="alert">
                  <CircleHelp size={18} aria-hidden="true" />
                  <p>{error}</p>
                </div>
              )}
              <button className="primary" type="submit" disabled={busy}>
                {busyAction === "account" && (
                  <LoaderCircle size={16} className="spin" aria-hidden="true" />
                )}
                {busyAction === "account"
                  ? mode === "signup"
                    ? "Creating account…"
                    : "Signing in…"
                  : mode === "signup"
                    ? "Create account"
                    : "Sign in"}
                {!busy && <ArrowRight size={16} aria-hidden="true" />}
              </button>
              <button
                className="text-button auth-mode"
                type="button"
                disabled={busy}
                onClick={() =>
                  changeMode(mode === "signin" ? "signup" : "signin")
                }
              >
                {mode === "signin"
                  ? "New here? Create an account"
                  : "Already have an account? Sign in"}
              </button>
            </form>
            {guestDemoEnabled && (
              <div>
                <h3>Explore as a guest</h3>
                <p>
                  Open a private director demo with labeled synthetic documents.
                  A temporary guest identity has no shared event, Gmail, or
                  payment access.
                </p>
                {guestError && (
                  <div className="auth-error" role="alert">
                    <CircleHelp size={18} aria-hidden="true" />
                    <p>{guestError}</p>
                  </div>
                )}
                <button
                  type="button"
                  onClick={startGuestDemo}
                  disabled={busy}
                  aria-busy={busyAction === "guest"}
                >
                  {busyAction === "guest" && (
                    <LoaderCircle
                      size={16}
                      className="spin"
                      aria-hidden="true"
                    />
                  )}
                  {busyAction === "guest"
                    ? "Opening private demo…"
                    : "Start private demo"}
                  {busyAction !== "guest" && (
                    <ArrowRight size={16} aria-hidden="true" />
                  )}
                </button>
              </div>
            )}
          </>
        )}
        <small className="auth-footnote">
          The event director connects Gmail separately. Your account does not
          grant mailbox access.
        </small>
      </div>
    </section>
  );
}
