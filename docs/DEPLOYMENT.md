# Deploying Finney

The intended layout is a Next.js dashboard on Vercel, event-owned Supabase for
Postgres/Auth/private Storage/Realtime, and a durable Python/Hermes worker on a
separate host. This is a deployment guide, not evidence of a completed deployment.
Public Vercel hosting, anonymous guest Auth, actual Coinbase testnet settlement
and measured live skill improvement remain unverified. See [validation](VALIDATION.md).

## Prepare Supabase and the worker

Follow the [root README](../README.md) from a clone of
[pauravhp/finney](https://github.com/pauravhp/finney). Configure an event-owned
Supabase project, apply the receipt-tracked migrations, create a real confirmed
director account and establish its private event membership. The Python package
and migrations live at this repository's root; there is no parent application
directory in the standalone repository.

On the worker host, install Python 3.11–3.13, uv and the pinned isolated Hermes
runtime. Keep root `.env` readable only by the service owner. Backend Supabase
secret/service-role credentials, model/Gateway keys, encryption keys and mailbox
or wallet grants belong on that host. Supabase stores durable application records
and encrypted grants; do not commit environment files or runtime profiles.

Run `uv run --frozen finance doctor` to inspect local readiness. The optional
`doctor --live` contacts configured providers and can incur model charges; it
does not prove the whole finance workflow. Start the foreground worker with:

```sh
uv run --frozen finance worker
```

Use the host's process supervisor with the repository as its working directory,
the protected environment, a unique `FINANCE_WORKER_ID`, and restart on failure.
Do not run the durable worker in a Vercel request or cron handler. Inspect actual
process status and persisted job/lease state after restart. See the
[operating manual](setup/manual.md#worker-supervision-and-recovery).

The default native Hermes Gmail connection uses the director's terminal consent
flow and needs no public mailbox callback service. Other members sign in with
email/password and do not grant mailbox access. Testnet wallet consent and funding
are separate optional setup; do not treat dashboard deployment as payment readiness.

## Configure Vercel

Import the standalone `pauravhp/finney` repository and choose:

| Setting | Value |
| --- | --- |
| Framework | Next.js |
| Root Directory | `web` |
| Node.js | 22 |
| Install command | `npm ci` |
| Build command | `npm run build` |
| Output directory | Next.js default |

Use [web/.env.example](../web/.env.example) as the variable-name reference. Set
`NEXT_PUBLIC_SUPABASE_URL` and `NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY` for the
intended project. Optional `NEXT_PUBLIC_FINANCE_ORGANIZATION_ID` and
`NEXT_PUBLIC_FINANCE_RUN_ID` choose initial scope; they grant no access.
All `NEXT_PUBLIC_*` values are public and baked into the browser build. A changed
value needs a new build. Keep Supabase secret/service-role keys, model keys,
encryption keys and OAuth secrets out of Vercel's web environment.

Leave `NEXT_PUBLIC_FINANCE_GUEST_DEMO=false` (or unset) for the default authenticated
entry. Enabling guest entry requires a separate deliberate Supabase anonymous
Auth and host-side anti-abuse configuration. The presence of the interface is not
evidence that public guest access has been verified.

`FINANCE_API_URL` is an optional server-only backend origin, not a provider key.
It is needed only for the legacy browser mailbox flow. If using that flow, run
`uv run --frozen finance oauth-server` on the backend host behind an HTTPS reverse
proxy, set `FINANCE_GMAIL_BACKEND=api` there, and point Vercel's `FINANCE_API_URL`
at that reachable HTTPS origin. Set the backend `GOOGLE_REDIRECT_URI` to its
`/oauth/gmail/callback` URL and register the exact URI with the Google Web OAuth
client. That callback is separate from Supabase dashboard authentication.
See [legacy mailbox setup](AUTH_SETUP.md#legacy-browser-mailbox-route).

## Configure dashboard authentication and live state

In Supabase Authentication URL Configuration, set **Site URL** to the actual
dashboard origin, such as `https://your-finney-domain.example`. Add the exact
`https://your-finney-domain.example/auth/callback` redirect URL. Add local
`http://127.0.0.1:3000/auth/callback` only when needed for local development.
Configure additional preview origins explicitly if you intend to use them.

Keep email/password Auth enabled. No Google SSO client is needed for dashboard
accounts. Configure email delivery for public signup/confirmation; the default
Supabase sender has recipient/rate restrictions. Sign up and open confirmation
in the same browser to complete the PKCE callback, then verify a real session.
An owner-provisioned confirmed account is a private-test fallback. See
[Auth setup](AUTH_SETUP.md) for the account and membership steps.

Disable public Supabase Realtime channels. The migrations authorize private
`finance:<organization_id>:<run_id>` subscriptions; the browser refetches on
change/reconnect and periodically recovers missed updates. Original documents,
extracted text, reports and procedure artifacts stay in private Storage.

## Verify the deployed flow

Check actual email/password sign-in and membership visibility at the deployed
origin. Submit a clearly labeled synthetic source and confirm the running worker
persists the real review, source references and status. Verify private document
download, a report artifact, and Realtime/reconnect recovery. Confirm the event's
approval policy: default two distinct humans, or explicitly selected one-director
mode; an agent never supplies a human approval.

Record deployment and live acceptance separately from [CI](../.github/workflows/ci.yml).
CI uses PostgreSQL platform stubs and browser fixtures without provider secrets;
it cannot establish hosted Auth delivery, live model accuracy, chain settlement
or improved financial performance. Do not reset uncertain payments or claim a
successful learning result to make a deployment check pass.
