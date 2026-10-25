"use client";

import { ArrowUpRight, RefreshCw } from "lucide-react";
import {
  walletApprovalUrl,
  type FinanceSnapshot,
  type PaymentJob,
  type PaymentSummary,
} from "@/lib/contracts";

type Proposal = FinanceSnapshot["approvals"][number];
type Props = {
  proposal: Proposal;
  payments: PaymentSummary[];
  jobs: PaymentJob[];
  canOperate: boolean;
  isDemo: boolean;
  busy: boolean;
  onExecute: (proposalId: string) => Promise<boolean>;
};

export function PaymentExecution({
  proposal,
  payments,
  jobs,
  canOperate,
  isDemo,
  busy,
  onExecute,
}: Props) {
  if (isDemo)
    return <p className="muted">Public demo runs cannot execute payments.</p>;
  if (!canOperate)
    return (
      <p className="muted">
        A current director or designated approver manages payment execution.
      </p>
    );
  const payment = payments.find((item) => item.proposal_id === proposal.id);
  const related = jobs.filter(
    (item) =>
      item.proposal_id === proposal.id &&
      (!item.payment_id || item.payment_id === payment?.id),
  );
  const latest = [...related].sort(
    (a, b) => Date.parse(b.created_at) - Date.parse(a.created_at),
  )[0];
  const activeJob = related.some((item) =>
    ["queued", "running"].includes(item.status),
  );
  const expired = Boolean(
    proposal.expires_at && Date.parse(proposal.expires_at) <= Date.now(),
  );
  const ready =
    (!payment || payment.status === "reserved") &&
    ["pending", "reserved"].includes(proposal.status) &&
    !expired &&
    proposal.approval_count >= proposal.required_approvals &&
    proposal.action.type === "payment";
  const approvalUrl =
    payment?.status === "uncertain" &&
    proposal.status === "reserved" &&
    !expired &&
    proposal.approval_count >= proposal.required_approvals
      ? walletApprovalUrl(payment.approval_url)
      : undefined;
  const status =
    payment?.status === "confirmed"
      ? "Confirmed on testnet"
      : activeJob
        ? "Payment work queued or running"
        : payment?.status === "submitted"
          ? "Awaiting chain confirmation"
          : payment?.status === "uncertain" && approvalUrl
            ? "Awaiting Wallet approval"
            : payment?.status === "uncertain"
              ? "Existing submission needs confirmation"
              : payment?.status === "submitting"
                ? "Submission requires confirmation"
                : payment?.status === "reserved"
                  ? "Funds reserved; not submitted"
                  : payment?.status === "failed"
                    ? "Payment failed"
                    : latest?.reason
                      ? "Payment is blocked"
                      : ready
                        ? "Ready for approved testnet execution"
                        : "Payment has not been submitted";
  const canReconcile = Boolean(
    payment?.can_reconcile &&
    ["uncertain", "submitted"].includes(payment.status),
  );
  return (
    <div className="payment-execution">
      <h3>Payment execution</h3>
      <p role="status">{status}</p>
      <p className="muted">
        {payment?.status === "confirmed"
          ? "The provider receipt was verified and the event ledger was updated."
          : payment?.status === "failed"
            ? "Review the failed payment before preparing a new action."
            : payment
              ? "Wallet approval and chain confirmation remain separate from the event’s human approvals. A pending request is not a confirmed payment."
              : "After the event’s approvals are complete, queue the exact testnet payment. Coinbase Wallet may require a separate confirmation."}
      </p>
      <dl className="action-facts">
        <div>
          <dt>Proposal</dt>
          <dd>{proposal.id}</dd>
        </div>
        {payment && (
          <div>
            <dt>Payment</dt>
            <dd>{payment.id}</dd>
          </div>
        )}
        {latest && (
          <div>
            <dt>Latest job</dt>
            <dd>{latest.id}</dd>
          </div>
        )}
        {payment?.provider_reference && (
          <div>
            <dt>Provider reference</dt>
            <dd>{payment.provider_reference}</dd>
          </div>
        )}
      </dl>
      {latest?.reason && payment?.status !== "confirmed" && (
        <p className="muted">
          Recorded reason: {latest.reason.replaceAll("_", " ")}
        </p>
      )}
      <div className="proposal-actions">
        {approvalUrl && (
          <a
            className="button"
            href={approvalUrl}
            target="_blank"
            rel="noopener noreferrer"
            referrerPolicy="no-referrer"
          >
            Open Wallet approval <ArrowUpRight size={15} aria-hidden="true" />
          </a>
        )}
        {canReconcile && (
          <button
            disabled={busy || activeJob}
            onClick={() => void onExecute(proposal.id)}
          >
            <RefreshCw size={15} aria-hidden="true" />
            Check existing payment
          </button>
        )}
        {ready && (
          <button
            className="primary"
            disabled={busy || activeJob}
            onClick={() => void onExecute(proposal.id)}
          >
            {payment
              ? "Resume approved testnet payment"
              : "Queue approved testnet payment"}
          </button>
        )}
      </div>
      {canReconcile && (
        <p className="muted">
          Check the same proposal’s existing request after Wallet approval. This
          queues provider reconciliation.
        </p>
      )}
    </div>
  );
}
