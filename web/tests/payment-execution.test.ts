import assert from "node:assert/strict";
import test from "node:test";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { PaymentExecution } from "../src/components/payment-execution";
import {
  paymentJobSchema,
  paymentSummarySchema,
  walletApprovalUrl,
  type FinanceSnapshot,
  type PaymentJob,
  type PaymentSummary,
} from "../src/lib/contracts";

const proposal: FinanceSnapshot["approvals"][number] = {
  id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
  action_hash: "fixture-exact-action-hash",
  action: {
    type: "payment",
    destination: "TEST ONLY recipient",
    amount_minor: "100",
    currency: "USD",
  },
  status: "reserved",
  required_approvals: 2,
  approval_count: 2,
  decisions: [],
  expires_at: "2099-01-01T00:00:00Z",
  created_at: "2026-10-25T00:00:00Z",
};
const payment: PaymentSummary = {
  id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
  proposal_id: proposal.id,
  status: "uncertain",
  provider_reference: "wallet-request:TEST-ONLY-request",
  approval_url: "https://wallet.example.invalid/approve/TEST-ONLY-request",
  can_reconcile: true,
  created_at: "2026-10-25T00:00:00Z",
  updated_at: "2026-10-25T00:00:00Z",
};
const job: PaymentJob = {
  id: "d19587c6-6535-4455-b4cd-ea4819845ec3",
  proposal_id: proposal.id,
  payment_id: payment.id,
  status: "blocked",
  outcome_status: "blocked",
  reason: "awaiting_coinbase_wallet_approval",
  provider_reference: payment.provider_reference,
  created_at: "2026-10-25T00:00:00Z",
  updated_at: "2026-10-25T00:00:00Z",
};
const props = {
  proposal,
  payments: [payment],
  jobs: [job],
  canOperate: true,
  isDemo: false,
  busy: false,
  onExecute: async () => true,
};
const view = (patch: Partial<typeof props> = {}) =>
  renderToStaticMarkup(createElement(PaymentExecution, { ...props, ...patch }));

test("pending Wallet request shows exact linkage and reconciliation without claiming payment", () => {
  const html = view();
  for (const id of [proposal.id, payment.id, job.id])
    assert.ok(html.includes(id));
  assert.match(html, /Awaiting Wallet approval/);
  assert.match(html, /Check existing payment/);
  assert.match(
    html,
    /href="https:\/\/wallet.example.invalid\/approve\/TEST-ONLY-request"/,
  );
  assert.match(html, /rel="noopener noreferrer"/);
  assert.match(html, /referrerPolicy="no-referrer"/i);
  assert.doesNotMatch(
    html,
    /Confirmed on testnet|ledger was updated|Queue approved testnet payment/,
  );
});

test("only eligible private-event users get provider links or payment controls", () => {
  for (const patch of [{ canOperate: false }, { isDemo: true }]) {
    const html = view(patch);
    assert.doesNotMatch(html, /href=|<button|wallet-request|TEST-ONLY-request/);
  }
  const stale = view({ proposal: { ...proposal, approval_count: 1 } });
  assert.doesNotMatch(stale, /href=/);
  assert.match(stale, /Check existing payment/);
  const expired = view({
    proposal: { ...proposal, expires_at: "2020-01-01T00:00:00Z" },
  });
  assert.doesNotMatch(expired, /href=/);
});

test("only the confirmed payment record produces confirmed copy", () => {
  const html = view({
    payments: [{ ...payment, status: "confirmed", can_reconcile: false }],
    jobs: [{ ...job, status: "completed", outcome_status: "completed" }],
  });
  assert.match(html, /Confirmed on testnet/);
  assert.doesNotMatch(html, /href=|<button/);
  assert.doesNotMatch(
    view({
      jobs: [{ ...job, status: "completed", outcome_status: "completed" }],
    }),
    /Confirmed on testnet/,
  );
});

test("initial execution requires recorded human approvals and active job disables duplicate queue", () => {
  const ready = {
    proposal: { ...proposal, status: "pending" },
    payments: [],
    jobs: [],
  };
  assert.match(view(ready), /Queue approved testnet payment/);
  assert.doesNotMatch(
    view({ ...ready, proposal: { ...ready.proposal, approval_count: 1 } }),
    /Queue approved testnet payment/,
  );
  assert.match(
    view({ jobs: [{ ...job, status: "running" }] }),
    /button disabled=""/,
  );
  assert.match(view({ busy: true }), /button disabled=""/);
});

test("malformed or credential-bearing URLs and foreign linkage cannot render provider capabilities", () => {
  for (const url of [
    "http://wallet.example.invalid/a",
    "javascript:alert(1)",
    "https://user:secret@wallet.example.invalid/a",
    "https:///",
    " https://wallet.example.invalid/a",
    "https://wallet.example.invalid/a\n",
  ]) {
    assert.equal(walletApprovalUrl(url), undefined);
    assert.doesNotMatch(
      view({ payments: [{ ...payment, approval_url: url }] }),
      /href=/,
    );
  }
  assert.doesNotMatch(
    view({ payments: [{ ...payment, proposal_id: payment.id }] }),
    /TEST-ONLY-request|href=/,
  );
});

test("payment contracts strip unknown worker output and preserve nullable safe metadata", () => {
  assert.equal(paymentSummarySchema.parse(payment).id, payment.id);
  const safe = paymentJobSchema.parse({
    ...job,
    result: { access_token: "TEST-ONLY-private" },
  });
  assert.equal("result" in safe, false);
  assert.equal(
    paymentJobSchema.safeParse({ ...job, reason: "private free-form output" })
      .success,
    false,
  );
});
