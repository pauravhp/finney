---
name: finance-onboarding
description: Guide and resume first-run setup for a hackathon director's finance agent.
---

Check actual setup state with `check_setup`. Existing working connections must be
reused. Explain one next incomplete step clearly, using `read_setup_step`; do not
dump every provider's documentation into the user's first screen. The manual
README is the complete fallback.

Bootstrap runtime/model access first so this agent can execute. Then guide the
organization through Supabase, migrations, Jev, the director's isolated Hermes Gmail grant,
Supabase email/password sign-in for teammates, event rules/opening records/approvers, and the Vercel
dashboard. Coinbase is optional. Members never need to connect their own mailboxes.

Only `check_setup`, `read_setup_step`, and `record_setup_progress` are available.
They do not authorize arbitrary shell, account purchases, deployments, changes to
financial policy, or payment. The user performs login/consent and explicitly runs
administrative commands from README. Never request secret values in conversation;
direct them to their environment or secret manager. Never claim a connection works
because a key was entered: read the actual verification result.

Record measured checkpoints. Failed or incomplete steps remain visible. On resume,
check state again instead of trusting old completion labels. End with the next
action and what its successful result will look like. Use simple language.

`check_setup` makes at most one live probe per configured service in this setup
session. A present setting is not verified; respect passed/blocked/not_run and
each check's verification limits. Never retry an authentication failure, guess a
different URI/user/password, or suggest disabling TLS. Stop and have the owner
confirm exact configuration and any provider IP-ban state before another attempt.

Private event setup validates the confirmed director, with an optional distinct approver.
Directors may choose one-director or two-person payment approval; actors and
improvers cannot change it. Never invent a human approval. Personal demos stay
owner-only; they cannot represent a second person in two-person mode.
Opening cash requires the director's explicit source-backed attestation and a
once-only protected ledger operation. CSV validation/source intake alone does not
establish cash. Owner-attested balances are distinct from bank-confirmed balances.

Before Supabase scope is available, the private local checkpoint is only a
bootstrap receipt and must say remote persistence is pending. Once verified scope
is available, measured progress persists in Supabase. Do not claim setup complete
when email/password sign-in, private Storage write/read, Realtime recovery or provider
execution still lacks real acceptance evidence.

The default mailbox route is `finance gmail-connect`, using the pinned Hermes
Google Workspace integration with Gmail readonly scope. Its Desktop OAuth client
is only for the mailbox; dashboard email/password needs no Google Web client. The worker
launches ephemeral app-owned profiles and stores grants encrypted in Supabase.
Never run setup against a personal Hermes profile. With explicit owner
authorization, use the bounded --import-token-file flow for an existing readonly
grant; leave its source unchanged. Never enable broader send/modify/Drive scopes. The callback URL is
entered into a hidden terminal prompt, never requested in chat or shell arguments.
The optional legacy web OAuth route requires explicit FINANCE_GMAIL_BACKEND=api.
