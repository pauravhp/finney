# Incident 001: hosted database authentication ban

October 24, 2026, Pacific. Coordinator-owned implementation failure.

After vault credentials were provided, the hosted REST API returned 200, but the
direct PostgreSQL URI failed. The coordinator made additional connection attempts
while trying to interpret/normalize URL formatting instead of stopping after an
authentication failure. Supabase temporarily banned the build host's IPv6 address.
The user noticed the dashboard warning. Local interface inspection confirmed an
exact match to the build host. No hosted database session succeeded; no hosted
migrations or table writes were performed during these attempts.

Containment: stopped all hosted DB attempts, checked that no probe process was
left running, instructed every builder to hold hosted access. Local tests continue.
The user removed the ban and subsequently confirmed replacing SUPABASE_DB_URL.
No agent removed the ban or changed routes/IPs to bypass it.

Correction: one explicit read-only verification using the exact updated URI,
offline syntax validation first, TLS required, no formatting guesses, no fallback
or retries. If it fails, stop and request correction. Outcome belongs in the
acceptance log; do not describe unbanning alone as a credential fix.

Resolution: the user-confirmed corrected URI succeeded on one TLS read-only
attempt at 2026-10-25 02:35 UTC (October 24 Pacific). PostgreSQL17.11 and an empty
public schema were observed. The coordinator subsequently applied migrations001,
002 and003 successfully; no authentication retry was needed. The retired
format-guessing probe scripts were removed. Builders remain prohibited from
uncoordinated hosted authentication probes.

Process lesson: treat authentication failure as a hard stop. Do not debug unknown
password/URI interpretations against a live service. Validate format offline,
obtain the corrected credential, then perform one controlled check. Redacted logs
are necessary but do not make repeated failed authentication acceptable.
