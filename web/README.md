# Director Finance web

The approved Organizer’s Desk landing is at `/`. Open `/desk` for the authenticated
finance workspace and sign-in. Existing links with an event/run scope still work.
Landing examples illustrate the product; live records and actual learning results
are shown only in the desk.

Next.js browser workspace for event-owned finance records in Supabase. The app
shows live scoped snapshots, source evidence, exact-action human approvals,
activity, recorded procedure improvement, report artifacts, and connection health.
It contains no seeded financial success data and can start without credentials to
show the explicit setup state.

## Local verification

Use Node 22 and npm 10 or newer:

```sh
npm ci
cp .env.example .env.local
npm run dev
```

Open <http://127.0.0.1:3000>. Add your event's actual Supabase URL and **publishable**
key to `.env.local`. Apply the finance migrations from `../supabase/migrations`.
No service-role key belongs in this app or its environment.

Use Supabase Auth's email/password provider. No Google SSO client is needed for
dashboard accounts. Supabase's allowed redirect URLs must
include `http://127.0.0.1:3000/auth/callback` and the eventual web deployment's
`https://<web-host>/auth/callback`. Set the project Site URL to the actual reachable
dashboard origin. Use the same browser to open the confirmation link that you
used to sign up; the callback exchanges the PKCE code for a real session.

Choose **Create an account**, submit an email/password, and confirm the email
when the project requires it. A sign-up response without a session stays in the
confirmation-pending state; it grants no workspace access. Supabase's default
hosted email service restricts recipients to project team addresses and has a
low email rate limit. Do not assume it can deliver sign-up links to arbitrary
visitors. The project owner can configure production email delivery later or
create confirmed accounts in Supabase Auth user management for the demo. This
application neither disables confirmation nor automatically creates accounts.
Password recovery is outside this interface's current scope; an owner can help
restore access through Supabase. See the [Supabase password-auth guide](https://supabase.com/docs/guides/auth/passwords).
The complete owner setup and account-bootstrap fallback are in
[AUTH_SETUP.md](../docs/AUTH_SETUP.md).

Signing in does not connect Gmail. The director separately connects the shared
event mailbox through isolated Hermes in the agent onboarding flow. Keep the
mailbox's Desktop OAuth client and permissions separate from dashboard accounts.

Authenticated members see their RLS-authorized organizations/runs. An account
without a membership can create a private empty demo via `create_finance_demo`.
Starting fresh cancels only that owner's selected demo run and creates a new
empty run; existing records remain auditable. Real source records, active worker,
provider connections, and the event's configured human approvals are still
required for execution. Payment policy defaults to two distinct eligible people;
the director can select director-only approval in Approvals. Changing this policy
invalidates pending payment proposals and approvals and is blocked while a payment
is in flight or awaiting settlement review.

`POST /api/finance/approval-policy` accepts the selected organization/run UUIDs,
`required_approvals` (1 or 2), and `expected_revision` from the current snapshot.
It verifies same-origin JSON, the server session, active director membership,
scope, and revision, then calls `set_event_approval_policy` with the user's
authenticated client. Database authorization and compare-and-swap checks still
apply. The dashboard displays the saved setting only after the service responds;
conflicts and payment-in-flight restrictions remain visible errors.

## Vercel configuration

Select `apps/director-finance/web` as the project root, Next.js as the framework,
`npm ci` for installation, and `npm run build` for the build. Set only:

- `NEXT_PUBLIC_SUPABASE_URL`
- `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY`
- Optionally `NEXT_PUBLIC_FINANCE_ORGANIZATION_ID` and `NEXT_PUBLIC_FINANCE_RUN_ID`
  as initial selectors. They grant no access; RLS still checks membership/ownership.

Disable public Supabase Realtime channels and use the migration's private channel
policy. Each browser subscribes to `finance:<organization_id>:<run_id>` and
refetches on `state_changed`, subscription/reconnect, and a 30-second recovery
poll. Lost access is shown as unavailable; stale data is labeled.

This package is deployment-ready configuration; no deployment has been performed.
The durable worker runs separately and needs its server-only credentials.

## Validation

```sh
npm test
npm run typecheck
npm run build
npm run test:browser
npm run test:auth-browser
```

The default browser suite runs **without Supabase configuration**, against the
production build on port 3317. It verifies desktop/mobile setup and empty states
plus route failure boundaries. `test:auth-browser` makes a separate build with
an explicit unusable `.invalid` Supabase origin and intercepts SDK responses in
Playwright only. It checks password-grant requests, errors, callback failure,
confirmation-pending behavior, email limits, and that passwords never enter
URLs, finance requests, cookies, or browser storage. The fixture runner restores
the normal `.next` build afterward, including after a test failure. Neither
browser suite creates accounts or sends email.

The suites use `/usr/bin/chromium` here; set
`PLAYWRIGHT_CHROMIUM_EXECUTABLE` to another Chromium executable when needed, or
install Playwright Chromium. They do not prove live email sign-in/delivery, RLS, private
Realtime, provider calls, or payment execution.

Server routes use cookie-authenticated `@supabase/ssr` clients with the publishable
key. Every mutation checks the same origin and validates its body; PostgreSQL
rechecks scope, capability, exact proposal hash, and immutable financial controls.
No browser route accepts a user-supplied role or actor identity. Money is decimal
string input, formatted through BigInt. Report downloads and procedure reads use
authenticated private Storage access rather than exposing a persistent public URL.

See `../docs/build/web.md` for acceptance evidence, failures, and remaining gates.

## Director-only Gmail connection

Set server-only `FINANCE_API_URL` to the coordinator backend's HTTPS origin
(loopback HTTP is accepted only for local development). `POST
/api/connectors/gmail/start` verifies the signed-in identity and forwards its
Supabase JWT to the fixed `/oauth/gmail/start` backend route. The backend checks
director authority and rejects personal demo runs. The returned destination must
be HTTPS `accounts.google.com`. OAuth state/authorization URLs are transient;
they are not written into activity or browser storage by this app.

Set backend `GOOGLE_REDIRECT_URI` to that backend's `/oauth/gmail/callback` URL.
This app's `/auth/callback` is for Supabase Auth email confirmations. There is no Gmail callback
proxy in this wave. Return to the workspace after backend confirmation to inspect
the actual connection record. Mail ingestion must remain limited to the explicitly
selected finance label/test thread. Missing Google OAuth setup is shown as blocked.

Personal demos are owner-only. Two-person approval tests require an actual shared
event run and two separate authenticated memberships; demo isolation is never
weakened to fabricate a second approver.
