import { snapshotSchema } from "../src/lib/contracts";

export const tutorialCaseId = "d19587c6-6535-4455-b4cd-ea4819845ec3";
export const tutorialSnapshot = snapshotSchema.parse({
  organization: {
    id: "d19587c6-6535-4455-b4cd-ea4819845ec1",
    name: "Tutorial fixture",
  },
  run: {
    id: "d19587c6-6535-4455-b4cd-ea4819845ec2",
    name: "Hack Harbor",
    status: "active",
    currency: "USD",
    revision: 1,
    scenario: {
      id: "fixture",
      title: "Hack Harbor",
      brief: "Synthetic test records",
      status: "ready",
      synthetic: true,
    },
  },
  position: {
    currency: "USD",
    cash_minor: "180000",
    committed_minor: "12000",
    receivable_minor: null,
    available_minor: null,
    evidence_status: "partial",
    reconciled_at: null,
  },
  cases: [
    {
      id: tutorialCaseId,
      title: "Changed AV invoice",
      status: "open",
      version: 1,
      data: {},
      updated_at: "2026-10-25T00:00:00Z",
    },
  ],
  approvals: [],
  activity: [],
  improvements: {
    skill_versions: [],
    eval_runs: [],
    eval_results: [],
    promotions: [],
  },
  connections: [],
  worker: { status: "online", last_seen_at: "2026-10-25T00:00:00Z" },
  updated_at: "2026-10-25T00:00:00Z",
});

export const tutorialFinding = (jobId: string) => ({
  kind: "prepared_agent_review",
  verification: "unverified_model_recommendation",
  effects_completed: false,
  decision: "needs_review",
  explanation: "The changed invoice needs your decision. No payment was made.",
  provenance: { job_id: jobId, actor_trace_id: "fixture-trace" },
});
