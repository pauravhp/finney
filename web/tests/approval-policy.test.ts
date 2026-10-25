import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { ApiError, type authenticated } from "../src/lib/api";
import { updateApprovalPolicy } from "../src/lib/approval-policy-server";
import { ApprovalPolicy } from "../src/components/approval-policy";
import { approvalPolicySchema, snapshotSchema } from "../src/lib/contracts";

const scope = {
  organization_id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  run_id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
};
// Local contract fixtures only: no account, database, or payment provider calls.
const snapshot = {
  organization: { id: scope.organization_id, name: "Policy unit fixture" },
  run: {
    id: scope.run_id,
    name: "Fixture",
    status: "active",
    currency: "USD",
    revision: 7,
    required_payment_approvals: 2,
    approval_policy_version: 1,
  },
  position: {
    currency: "USD",
    cash_minor: null,
    committed_minor: null,
    receivable_minor: null,
    available_minor: null,
    evidence_status: "unknown",
    reconciled_at: null,
  },
  cases: [],
  approvals: [],
  activity: [],
  connections: [],
  improvements: {
    skill_versions: [],
    eval_runs: [],
    eval_results: [],
    promotions: [],
  },
  worker: { status: "unknown", last_seen_at: null },
  updated_at: "2026-10-25T00:00:00Z",
};
const body = { ...scope, required_approvals: 1, expected_revision: 7 };
const result = {
  ...scope,
  required_payment_approvals: 1,
  approval_policy_version: 2,
  revision: 8,
};
function request(
  data: unknown = body,
  origin = "https://finance.example.test",
) {
  return new Request(
    "https://finance.example.test/api/finance/approval-policy",
    {
      method: "POST",
      headers: { origin, "content-type": "application/json" },
      body: JSON.stringify(data),
    },
  );
}
function fixture(
  options: {
    role?: string | null;
    rpcError?: { code: string; message: string };
    snapshot?: unknown;
    result?: unknown;
  } = {},
) {
  const calls: { name: string; args: unknown }[] = [];
  const filters: unknown[][] = [];
  const query = {
    select() {
      return query;
    },
    eq(...args: unknown[]) {
      filters.push(args);
      return query;
    },
    async maybeSingle() {
      return {
        data:
          options.role === null ? null : { role: options.role ?? "director" },
        error: null,
      };
    },
  };
  const authenticate = async () => ({
    user: { id: "verified-session-user" },
    supabase: {
      from(name: string) {
        assert.equal(name, "memberships");
        return query;
      },
      async rpc(name: string, args: unknown) {
        calls.push({ name, args });
        return name === "get_finance_snapshot"
          ? { data: options.snapshot ?? snapshot, error: null }
          : { data: options.result ?? result, error: options.rpcError ?? null };
      },
    },
  });
  return {
    calls,
    filters,
    authenticate: authenticate as unknown as typeof authenticated,
  };
}

test("policy contract permits only 1 or 2 and exact safe revision, never caller authority", () => {
  assert.equal(approvalPolicySchema.safeParse(body).success, true);
  for (const patch of [
    { required_approvals: 0 },
    { required_approvals: 3 },
    { required_approvals: "1" },
    { expected_revision: -1 },
    { expected_revision: 0.5 },
    { expected_revision: Number.MAX_SAFE_INTEGER + 1 },
    { role: "director" },
    { user_id: "spoofed" },
  ])
    assert.equal(
      approvalPolicySchema.safeParse({ ...body, ...patch }).success,
      false,
    );
  const legacy = snapshotSchema.parse({
    ...snapshot,
    run: {
      ...snapshot.run,
      required_payment_approvals: undefined,
      approval_policy_version: undefined,
    },
  });
  assert.equal(legacy.run.required_payment_approvals, 2);
  assert.equal(legacy.run.approval_policy_version, 1);
});

test("foreign origin, malformed policy and expired authentication never call database RPCs", async () => {
  const f = fixture();
  assert.equal(
    (
      await updateApprovalPolicy(
        request(body, "https://foreign.invalid"),
        f.authenticate,
      )
    ).status,
    403,
  );
  assert.equal(
    (
      await updateApprovalPolicy(
        request({ ...body, required_approvals: 3 }),
        f.authenticate,
      )
    ).status,
    400,
  );
  const expired = await updateApprovalPolicy(request(), async () => {
    throw new ApiError(401, "Your session has expired.");
  });
  assert.equal(expired.status, 401);
  assert.deepEqual(f.calls, []);
});

test("only a current director membership can reach policy RPC", async () => {
  for (const role of ["viewer", "approver", "finance_member", null]) {
    const f = fixture({ role });
    assert.equal(
      (await updateApprovalPolicy(request(), f.authenticate)).status,
      403,
    );
    assert.deepEqual(f.calls, []);
    assert.deepEqual(f.filters, [
      ["organization_id", scope.organization_id],
      ["user_id", "verified-session-user"],
      ["active", true],
    ]);
  }
});

test("wrong scope and stale revision never reach mutation RPC", async () => {
  const stale = fixture();
  assert.equal(
    (
      await updateApprovalPolicy(
        request({ ...body, expected_revision: 6 }),
        stale.authenticate,
      )
    ).status,
    409,
  );
  assert.equal(stale.calls.length, 1);
  const wrong = fixture({
    snapshot: {
      ...snapshot,
      run: { ...snapshot.run, id: scope.organization_id },
    },
  });
  assert.equal(
    (await updateApprovalPolicy(request(), wrong.authenticate)).status,
    403,
  );
  assert.equal(wrong.calls.length, 1);
});

test("authenticated director receives authoritative result from CAS mutation", async () => {
  const f = fixture();
  const response = await updateApprovalPolicy(request(), f.authenticate);
  assert.equal(response.status, 200);
  assert.deepEqual(await response.json(), result);
  assert.match(response.headers.get("cache-control") ?? "", /no-store/);
  assert.deepEqual(f.calls[1], {
    name: "set_event_approval_policy",
    args: {
      p_organization_id: scope.organization_id,
      p_run_id: scope.run_id,
      p_required_approvals: 1,
      p_expected_revision: 7,
    },
  });
});

test("database authorization, concurrent revision and payment in flight remain failures with actionable copy", async () => {
  for (const [code, message, status, text] of [
    ["42501", "director only", 403, /access/],
    ["40001", "approval policy revision changed", 409, /changed while saving/],
    [
      "23514",
      "unsettled payments prevent approval policy change",
      409,
      /payment is in flight/,
    ],
  ] as const) {
    const f = fixture({ rpcError: { code, message } });
    const response = await updateApprovalPolicy(request(), f.authenticate);
    assert.equal(response.status, status);
    assert.match((await response.json()).error, text);
  }
});

test("incompatible or cross-run mutation result cannot produce success", async () => {
  for (const returned of [
    {},
    { ...result, run_id: scope.organization_id },
    { ...result, required_payment_approvals: 2 },
  ]) {
    const f = fixture({ result: returned });
    assert.equal(
      (await updateApprovalPolicy(request(), f.authenticate)).status,
      502,
    );
  }
});

test("all members see current policy while only directors receive the policy control", () => {
  for (const required of [1, 2] as const) {
    const run = {
      ...snapshotSchema.parse(snapshot).run,
      required_payment_approvals: required,
    };
    const view = (canEdit: boolean) =>
      renderToStaticMarkup(
        createElement(ApprovalPolicy, {
          run,
          canEdit,
          busy: false,
          onSave: async () => {},
        }),
      );
    assert.match(
      view(false),
      required === 1
        ? /Current setting:.*Director approval only/
        : /Current setting:.*Two distinct eligible people/,
    );
    assert.doesNotMatch(view(false), /<select/);
    assert.match(view(true), /<select/);
    assert.match(
      view(true),
      /invalidates pending payment proposals and their approvals/,
    );
    assert.match(view(true), /Save approval policy/);
  }
});
