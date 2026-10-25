# Director-only private event setup

October 25, 2026. User authorized using the confirmed owner test account as
director and connecting its Gmail. This change removes the second participant
as a prerequisite for private event creation; payment authority is unchanged.

`finance event-sql` accepts an optional `--approver-user-id`. With only a director,
it validates the existing confirmed nonanonymous email/password identity, creates
one director membership and a durable private run (`is_demo=false`) with that
owner, and reports `approver_configured=false`. It creates no Auth users, funds,
cash, approvals or payments. With an explicit approver it retains both identity
checks and requires distinct user IDs. Existing plan IDs remain stable; changed
plan inputs, mismatched owners/demo runs and wrong-role/inactive existing
memberships are rejected rather than changed.

Validation used the explicit loopback PostgreSQL cluster, with fresh random
databases and fixture Auth identities. No hosted access, email, Gmail consent or
personal Hermes access occurred in these checks.

```sh
FINANCE_TEST_DB_URL=postgresql://postgres:postgres@127.0.0.1:5432/postgres .venv/bin/pytest tests/test_packaging.py tests/test_packaging_postgres.py -q
.venv/bin/ruff check app/event_setup.py app/cli.py tests/test_packaging.py tests/test_packaging_postgres.py
```

Result: **43 tests passed in 3.29 seconds; Ruff passed.** This is local setup
evidence, not proof of hosted event provisioning or mailbox consent. New SQL
integration cases cover director-only reruns, zero financial records, missing or
ineligible directors, owner/privacy mismatches, and refusing promotion/reactivation
of pre-existing director or approver memberships. Existing two-user cases pass.
No test failures were observed during this change.

Reusable lesson: creating the private event and connecting its director's mailbox
can proceed independently from enrolling the second payment approver. Keep the
two-human requirement at financial authorization and execution boundaries.
