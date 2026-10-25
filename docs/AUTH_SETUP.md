# Dashboard sign-in and the director's mailbox

The dashboard uses **Supabase email/password authentication**. Google SSO is no
longer required. Only the director separately authorizes Gmail through the
isolated Hermes runtime. A dashboard session does not confer mailbox access.

## Supabase email/password

1. In Supabase → Authentication → Sign In / Providers, ensure Email is enabled
   (Supabase enables it by default). No Google Cloud Web client or Google provider
   configuration is required.
2. Set the dashboard's public Supabase URL/publishable key. In Supabase URL
   Configuration, use the actual dashboard origin as Site URL and allow that
   origin's `/auth/callback`. For a local checkout, use
   `http://127.0.0.1:3000` and `http://127.0.0.1:3000/auth/callback`. Add the real
   Vercel origin when deployed. Your laptop's localhost is not this build host.
3. Use the dashboard's Create account form. When confirmation is enabled, the
   app reports that confirmation is pending; it does not pretend a session exists.
   Confirm the email, then sign in with email/password. Membership comes from
   explicit event setup, not merely account creation.
4. For a private demo, the project owner can create actual participants'
   password accounts through Supabase Authentication → Users, marking their
   known emails confirmed. Each person then signs in with their account. Never
   create fictional identities and claim they are a second human approval.
5. Copy the director's real Auth Users UUID into README's `finance event-sql`
   command. It accepts a confirmed, nonanonymous email/password identity and
   creates a durable private event owned by that director. An approver is optional
   at setup: include `--approver-user-id` only for a distinct real participant.
   Without one, the result reports `approver_configured=false`; Gmail setup and
   financial review can proceed. The director selects one-director or two-person
   approval in the Approvals panel; default two-person mode still needs distinct
   eligible real people. Changing policy invalidates old pending approvals.
   No funds, cash or synthetic approver are created. The protected bootstrap plan
   preserves IDs and rejects changed membership inputs; adding a later approver
   requires an explicit membership change. Event setup does not require a Google
   identity or grant teammates access to the director's mailbox.

No app/database table stores passwords; the Supabase Auth SDK handles sign-in.
The user enters a password in the browser. It never goes into finance commands,
logs, URLs, traces or source files. Owner provisioning is not public signup.

Supabase's default email sender is limited to project-team addresses and has low
sending limits. Use configured SMTP before promising signup confirmation/recovery
for arbitrary public users. Creating confirmed demo accounts avoids that delivery
step; it does not prove email delivery. No confirmation settings are automatically
disabled, and this implementation does not send test emails or create accounts.
[Supabase email delivery](https://supabase.com/docs/guides/auth/auth-smtp).

## Hermes Gmail

Enable Gmail API and create an OAuth client with type **Desktop app**, named
“Finney mailbox”. Download its JSON privately. This client belongs to the isolated
finance application; do not import personal Hermes credentials or change its
profile. The app requests Gmail readonly scope and restricts intake to the
configured finance label. The scope itself grants mailbox read access.

Follow README step 7: `finance gmail-connect --client-file PATH
--director-user-id UUID`, then `finance gmail-connect --complete`. The generated
authorization URL is opened in your browser; the full localhost redirect URL is
entered only at the hidden terminal prompt on the worker host. No reachable
backend OAuth callback service is required for this headless Hermes path.

The source-pinned Hermes setup and Gmail client run in fresh, private temporary
profiles. They cannot discover the owner's personal Gmail/CLI profile through
the child environment. This is application capability isolation, not an OS
sandbox for untrusted host programs. Supabase stores encrypted authorization
state/grants; the encryption key remains in the owner's protected configuration.

Public distribution of Gmail readonly access must account for Google's applicable
verification requirements. Testing configuration and a successful local adapter
test do not establish Google approval or a real mailbox grant.

## Legacy browser mailbox route

Set `FINANCE_GMAIL_BACKEND=api`, configure a separate Gmail **Web application**
client via `GOOGLE_CLIENT_ID`, `GOOGLE_CLIENT_SECRET` and `GOOGLE_REDIRECT_URI`,
and register that exact callback with Google. The local default is
`http://127.0.0.1:8767/oauth/gmail/callback`. Run `finance oauth-server` and set
the dashboard's server-only `FINANCE_API_URL` to its reachable origin. The director
can then use Connect event Gmail in a shared event run. Hosting requires an HTTPS
backend reachable from both the dashboard server and the user's browser.
This route remains explicit; a failed Hermes call never falls back to it.

References: [Supabase password auth](https://supabase.com/docs/guides/auth/passwords),
[Google Desktop OAuth](https://developers.google.com/identity/protocols/oauth2/native-app),
[Hermes Workspace](https://hermes-agent.nousresearch.com/docs/user-guide/skills/google-workspace).

## Reuse an existing readonly Google grant

With the owner's explicit authorization, `finance gmail-connect --import-token-file
PATH --expected-mailbox ADDRESS --director-user-id UUID` imports a selected
owner-private authorized-user token JSON. It verifies exact readonly scope, the
expected mailbox and current director/private-event authority before atomic
encrypted storage. It never edits the original token, profile or runtime. Refresh
occurs only in an ephemeral app profile; consent/client creation is unnecessary
when the existing grant remains valid.

Reusing a grant also shares its underlying Google authorization. Removing Finney's
connection must not automatically revoke that provider grant and disrupt the
original integration. Local profiles remain separate.
