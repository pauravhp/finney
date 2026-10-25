"use client";

import { useEffect, useState } from "react";
import { ShieldCheck } from "lucide-react";
import type { FinanceSnapshot } from "@/lib/contracts";

export function paymentApprovalLabel(required: number) {
  return required === 1
    ? "Director approval only"
    : "Two distinct eligible people";
}

export function ApprovalPolicy({
  run,
  canEdit,
  busy,
  onSave,
}: {
  run: FinanceSnapshot["run"];
  canEdit: boolean;
  busy: boolean;
  onSave: (required: 1 | 2, revision: number) => Promise<void>;
}) {
  const [required, setRequired] = useState<1 | 2>(
    run.required_payment_approvals,
  );
  const [failure, setFailure] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);
  const [saving, setSaving] = useState(false);
  useEffect(() => {
    setRequired(run.required_payment_approvals);
  }, [run.required_payment_approvals]);
  const changed = required !== run.required_payment_approvals;
  return (
    <section
      className="approval-policy"
      aria-labelledby="approval-policy-title"
    >
      <div className="approval-policy-heading">
        <ShieldCheck size={22} aria-hidden="true" />
        <div>
          <h2 id="approval-policy-title">Payment approval policy</h2>
          <p>
            Current setting:{" "}
            <strong>
              {paymentApprovalLabel(run.required_payment_approvals)}
            </strong>
          </p>
          <p>
            Policy version {run.approval_policy_version}. Each payment binds its
            exact action to this policy.
          </p>
        </div>
      </div>
      {canEdit ? (
        <form
          onSubmit={async (event) => {
            event.preventDefault();
            if (!changed || busy) return;
            setFailure(null);
            setSaved(false);
            setSaving(true);
            try {
              await onSave(required, run.revision);
              setSaved(true);
            } catch (error) {
              setFailure(
                error instanceof Error
                  ? error.message
                  : "The approval policy could not be saved. Refresh and try again.",
              );
            } finally {
              setSaving(false);
            }
          }}
        >
          <label htmlFor="required-payment-approvals">
            Required payment approvals
          </label>
          <div className="approval-policy-controls">
            <select
              id="required-payment-approvals"
              value={required}
              disabled={busy}
              onChange={(event) => {
                setRequired(Number(event.target.value) as 1 | 2);
                setSaved(false);
                setFailure(null);
              }}
              aria-describedby="approval-policy-effect"
            >
              <option value={1}>1 — Director approval only</option>
              <option value={2}>2 — Two distinct eligible people</option>
            </select>
            <button
              className="primary"
              disabled={!changed || busy}
              type="submit"
            >
              {saving ? "Saving policy…" : "Save approval policy"}
            </button>
          </div>
          <p id="approval-policy-effect">
            Changing this setting invalidates pending payment proposals and
            their approvals. Prepare and review new proposals under the new
            policy. A payment in flight or awaiting settlement review blocks
            changes.
          </p>
          {changed && required === 1 && (
            <p className="approval-policy-impact">
              The director will be able to approve a payment alone, including a
              payment they proposed.
            </p>
          )}
          {failure && (
            <p role="alert" className="approval-policy-error">
              {failure}
            </p>
          )}
          {saved && (
            <p role="status" className="approval-policy-saved">
              The finance service saved the approval policy. Pending proposals
              must be prepared again.
            </p>
          )}
        </form>
      ) : (
        <p className="approval-policy-readonly">
          Only the event director can change this setting.
        </p>
      )}
    </section>
  );
}
