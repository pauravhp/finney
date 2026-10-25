# Product

<!-- impeccable:product-schema 1 -->

## Platform

web

## Stack

Next.js on Vercel, Supabase Auth/Postgres/Storage/Realtime, and a durable finance
worker running app-owned OpenCode + Harness2. Pinned Hermes helpers provide Gmail.

## Users

Hackathon directors and finance members who need to understand budgets, inspect
obligations and evidence, respond to approval requests, and ask the agent to work.

## Product Purpose

Finney is a finance teammate for event organizers. It investigates source records,
keeps work and uncertainty inspectable, and proposes procedure improvements that
must pass independent evaluation before activation.

## Capabilities and Constraints

The browser reads scoped live state and queues work through authenticated APIs.
It cannot directly approve on someone’s behalf, change financial balances, or
promote a learned candidate. Directors retain approval authority under the event’s
versioned policy. Unknown values and rejected learning attempts remain visible.
The landing uses disclosed financial illustrations; `/desk` is the actual app.

## Brand Commitments

Use the owner-approved Organizer’s Desk v7: Albert Sans, mint/ink/white, pale green
working surfaces, colored landing folders and the animated receipt character.
Preserve the approved design instead of inventing another direction.

## Evidence on Hand

Operating and learning acceptance are documented in `../docs/build/`. The design
illustration is not a measured promotion. The first evaluated candidate improved
validation but failed final heldout evaluation and remained inactive.

## Product Principles

- Keep financial decisions connected to the records and policy behind them.
- Let the director ask a new question without waiting for background work to end.
- Ask for approval at the appropriate stage and respect a refusal.
- Show queued work, completed effects and uncertain results distinctly.
- Make learned changes earn activation through the unchanged protected gates.
