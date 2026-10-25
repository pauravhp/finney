import assert from "node:assert/strict";
import test from "node:test";
import {
  approvalSchema,
  assertSnapshotScope,
  commandSchema,
  demoSchema,
  displayRecord,
  formatMoney,
  safeEvidenceUrl,
  snapshotSchema,
} from "../src/lib/contracts";

const organization_id = "d19587c6-6535-4455-b4cd-ea4819845ec1";
const run_id = "d19587c6-6535-4455-b4cd-ea4819845ec2";
const scope = { organization_id, run_id };
// Unit contract input only. This fixture is never imported by the application.
const fixture = {
  organization: { id: organization_id, name: "Contract test" },
  run: {
    id: run_id,
    name: "Unit fixture",
    status: "active",
    currency: "USD",
    revision: 0,
  },
  position: {
    currency: "USD",
    cash_minor: null,
    committed_minor: "9007199254740993123",
    receivable_minor: "0",
    available_minor: null,
    evidence_status: "unknown",
    reconciled_at: null,
  },
  cases: [],
  approvals: [],
  activity: [],
  improvements: {
    skill_versions: [],
    eval_runs: [],
    eval_results: [],
    promotions: [],
  },
  connections: [],
  worker: { status: "unknown", last_seen_at: null },
  updated_at: "2026-10-25T00:00:00Z",
};

test("money remains exact beyond JavaScript's safe integer range", () => {
  assert.equal(
    formatMoney("9007199254740993123", "USD"),
    "US$90,071,992,547,409,931.23",
  );
  assert.equal(formatMoney("-1", "USD"), "−US$0.01");
  assert.equal(formatMoney(null, "USD"), "Unknown");
  assert.equal(formatMoney("123", "JPY"), "JP¥123");
  assert.equal(formatMoney("1234", "KWD"), "KWD 1.234");
});

test("snapshot rejects imprecise numeric money and keeps unknown separate from zero", () => {
  const parsed = snapshotSchema.parse(fixture);
  assert.equal(parsed.position.cash_minor, null);
  assert.equal(parsed.position.committed_minor, "9007199254740993123");
  assert.equal(
    snapshotSchema.safeParse({
      ...fixture,
      position: { ...fixture.position, cash_minor: 0 },
    }).success,
    false,
  );
});

test("a valid snapshot from another visitor run is rejected", () => {
  const parsed = snapshotSchema.parse(fixture);
  assert.throws(
    () =>
      assertSnapshotScope(parsed, {
        ...scope,
        run_id: "d19587c6-6535-4455-b4cd-ea4819845ec3",
      }),
    /different run/,
  );
});

test("commands cannot smuggle caller roles, financial writes, or unsupported work types", () => {
  const command = {
    ...scope,
    command_type: "intake",
    payload: { instruction: "Review selected source" },
    idempotency_key: "request-123",
  };
  assert.equal(commandSchema.safeParse(command).success, true);
  assert.equal(
    commandSchema.safeParse({ ...command, role: "director" }).success,
    false,
  );
  assert.equal(
    commandSchema.safeParse({ ...command, command_type: "set_balance" })
      .success,
    false,
  );
  assert.equal(
    commandSchema.safeParse({ ...command, idempotency_key: "" }).success,
    false,
  );
});

test("approval requires exact hash and never accepts an actor identity", () => {
  const proposal = {
    ...scope,
    proposal_id: run_id,
    expected_action_hash: "exact-provider-action-hash",
    decision: "approve",
  };
  assert.equal(approvalSchema.safeParse(proposal).success, true);
  assert.equal(
    approvalSchema.safeParse({ ...proposal, user_id: organization_id }).success,
    false,
  );
  assert.equal(
    approvalSchema.safeParse({ ...proposal, expected_action_hash: "" }).success,
    false,
  );
});

test("demo reset only accepts a specific previous run ID", () => {
  assert.deepEqual(demoSchema.parse({ name: "My demo" }), {
    name: "My demo",
    previous_run_id: null,
  });
  assert.equal(
    demoSchema.safeParse({ name: "reset", reset_all: true }).success,
    false,
  );
});

test("untrusted source URLs cannot execute browser code", () => {
  for (const value of [
    "javascript:alert(1)",
    "data:text/html,<script>",
    "/api/private",
    "http://unsafe.invalid",
  ])
    assert.equal(safeEvidenceUrl(value), undefined);
  assert.equal(
    safeEvidenceUrl("https://example.org/source"),
    "https://example.org/source",
  );
});

test("record inspection hides secret and ephemeral credential fields recursively", () => {
  const protectedData = displayRecord({
    nested: [
      {
        access_token: "secret",
        authorization_url: "https://auth.invalid?state=secret",
        download_url: "https://storage.invalid?token=secret",
      },
    ],
    state: "promoted",
    content_sha256: "hash",
  });
  assert.equal(JSON.stringify(protectedData).includes("secret"), false);
  assert.equal((protectedData as Record<string, unknown>).state, "promoted");
});

test("mailbox authorization redirects only to the actual Google HTTPS origin", async () => {
  const { googleAuthorizationUrl } = await import("../src/lib/connectors");
  assert.equal(
    googleAuthorizationUrl(
      "https://accounts.google.com/o/oauth2/v2/auth?state=ephemeral",
    ),
    "https://accounts.google.com/o/oauth2/v2/auth?state=ephemeral",
  );
  for (const url of [
    "https://accounts.google.com.evil.invalid/auth",
    "http://accounts.google.com/auth",
    "https://user:pass@accounts.google.com/auth",
    "javascript:alert(1)",
  ])
    assert.equal(googleAuthorizationUrl(url), null);
});

test("opening cash form preserves exact units, permits zero, and requires real owner attestation", async () => {
  const { openingCashPayload, parseMajorUnits } =
    await import("../src/lib/contracts");
  const input = {
    amount: "90071992547409.93",
    currency: "USD",
    as_of: "2026-10-24",
    note: "Owner account statement",
    attested: true,
  };
  assert.equal(openingCashPayload(input).amount_minor, "9007199254740993");
  assert.equal(openingCashPayload({ ...input, amount: "0" }).amount_minor, "0");
  assert.equal(parseMajorUnits("1.234", "KWD"), "1234");
  for (const amount of ["1.001", "-1", "NaN", "1e3", "92233720368547758.08"])
    assert.throws(() => openingCashPayload({ ...input, amount }));
  assert.throws(() => openingCashPayload({ ...input, attested: false }));
  assert.throws(() => openingCashPayload({ ...input, as_of: "2026-02-30" }));
  assert.throws(() => openingCashPayload({ ...input, note: " " }));
});
