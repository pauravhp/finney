import { z } from "zod";

export const uuid = z.uuid();
export const scopeSchema = z.object({ organization_id: uuid, run_id: uuid });
export const uploadLinkSchema = z
  .object({
    case_id: uuid.optional(),
    replaces_source_id: uuid.optional(),
  })
  .strict()
  .refine((value) => !value.replaces_source_id || Boolean(value.case_id), {
    message: "Choose a case before replacing its source.",
    path: ["case_id"],
  });
const record = z.record(z.string(), z.unknown());
const money = z
  .string()
  .regex(/^-?\d+$/)
  .nullable();
export const commandTypes = [
  "intake",
  "review_case",
  "refresh_forecast",
  "generate_report",
  "evaluate_improvement",
  "execute_payment",
  "director_message",
] as const;
export const commandSchema = scopeSchema
  .extend({
    command_type: z.enum(commandTypes),
    payload: record.default({}),
    idempotency_key: z.string().min(8).max(200),
  })
  .strict();
export const approvalSchema = scopeSchema
  .extend({
    proposal_id: uuid,
    expected_action_hash: z.string().min(1).max(200),
    decision: z.enum(["approve", "reject"]),
  })
  .strict();
export const approvalPolicySchema = scopeSchema
  .extend({
    required_approvals: z.union([z.literal(1), z.literal(2)]),
    expected_revision: z
      .number()
      .int()
      .nonnegative()
      .max(Number.MAX_SAFE_INTEGER),
  })
  .strict();
export const approvalPolicyResultSchema = scopeSchema.extend({
  required_payment_approvals: z.union([z.literal(1), z.literal(2)]),
  approval_policy_version: z
    .number()
    .int()
    .positive()
    .max(Number.MAX_SAFE_INTEGER),
  revision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
});
export const demoSchema = z
  .object({
    name: z.string().min(1).max(100).default("Finance demo"),
    previous_run_id: uuid.nullable().default(null),
  })
  .strict();
export const paymentSummarySchema = z.object({
  id: uuid,
  proposal_id: uuid,
  status: z.enum([
    "reserved",
    "submitting",
    "uncertain",
    "submitted",
    "confirmed",
    "failed",
  ]),
  provider_reference: z.string().max(512).nullable(),
  approval_url: z.string().max(4096).nullable(),
  can_reconcile: z.boolean(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const paymentJobSchema = z.object({
  id: uuid,
  proposal_id: uuid,
  payment_id: uuid.nullable(),
  status: z.enum([
    "queued",
    "running",
    "completed",
    "failed",
    "blocked",
    "cancelled",
  ]),
  outcome_status: z
    .enum(["completed", "blocked", "failed", "pending_verification"])
    .nullable(),
  reason: z
    .string()
    .regex(/^[a-z][a-z0-9_]{0,119}$/)
    .nullable(),
  provider_reference: z.string().max(512).nullable(),
  created_at: z.string(),
  updated_at: z.string(),
});
export const snapshotSchema = z.object({
  jobs: z.array(record).default([]),
  payment_jobs: z.array(paymentJobSchema).default([]),
  payments: z.array(paymentSummarySchema).default([]),
  budget: z
    .object({ lines: z.array(record), decisions: z.array(record) })
    .default({ lines: [], decisions: [] }),
  organization: z.object({ id: uuid, name: z.string() }),
  run: z.object({
    id: uuid,
    name: z.string(),
    status: z.string(),
    currency: z.string(),
    revision: z.number().int().nonnegative().max(Number.MAX_SAFE_INTEGER),
    scenario: z
      .object({
        id: z.string(),
        title: z.string(),
        brief: z.string(),
        status: z.string().optional(),
        seed_status: z.string().optional(),
        seed_retry_available: z.boolean().optional(),
        seed_attempts: z.number().optional(),
        seed_attempt_limit: z.number().optional(),
        seed_error_code: z.string().nullable().optional(),
        synthetic: z.literal(true),
        steps: z
          .array(
            z.object({
              id: z.string(),
              title: z.string(),
              case_id: uuid.nullable().optional(),
              prompt: z.string().optional(),
            }),
          )
          .optional(),
      })
      .nullable()
      .optional(),
    required_payment_approvals: z
      .union([z.literal(1), z.literal(2)])
      .default(2),
    approval_policy_version: z.number().int().positive().default(1),
  }),
  position: z.object({
    currency: z.string(),
    cash_minor: money,
    committed_minor: money,
    receivable_minor: money,
    available_minor: money,
    evidence_status: z.string(),
    reconciled_at: z.string().nullable(),
  }),
  cases: z.array(
    z.object({
      id: uuid,
      title: z.string(),
      status: z.string(),
      version: z.number(),
      data: record,
      updated_at: z.string(),
    }),
  ),
  approvals: z.array(
    z.object({
      id: uuid,
      action_hash: z.string(),
      action: record,
      status: z.string(),
      required_approvals: z.number(),
      approval_count: z.number(),
      decisions: z.array(record),
      expires_at: z.string().nullable(),
      created_at: z.string(),
    }),
  ),
  activity: z.array(
    z.object({
      id: z.union([z.number(), z.string()]),
      event_type: z.string(),
      payload: record,
      created_at: z.string(),
    }),
  ),
  improvements: z.object({
    trace_events: z.array(record).default([]),
    skill_versions: z.array(record),
    eval_runs: z.array(record),
    eval_results: z.array(record),
    promotions: z.array(record),
  }),
  connections: z.array(record),
  obligations: z
    .array(
      z.object({
        id: uuid,
        title: z.string(),
        direction: z.string(),
        amount_minor: money,
        settled_minor: money,
        currency: z.string(),
        status: z.string(),
        evidence_status: z.string(),
        source_refs: z.array(z.unknown()),
      }),
    )
    .default([]),
  source_items: z.array(record).default([]),
  reports: z.array(record).default([]),
  worker: z.object({ status: z.string(), last_seen_at: z.string().nullable() }),
  updated_at: z.string(),
});

export type FinanceSnapshot = z.infer<typeof snapshotSchema>;
export type PaymentSummary = z.infer<typeof paymentSummarySchema>;
export type PaymentJob = z.infer<typeof paymentJobSchema>;
export type Scope = z.infer<typeof scopeSchema>;
export type FinanceCommand = (typeof commandTypes)[number];
export type ScopeChoice = {
  organization_id: string;
  organization_name: string;
  role: string;
  runs: { id: string; name: string; status: string; is_demo: boolean }[];
};

export function assertSnapshotScope(snapshot: FinanceSnapshot, scope: Scope) {
  if (
    snapshot.organization.id !== scope.organization_id ||
    snapshot.run.id !== scope.run_id
  )
    throw new Error("The returned financial state belongs to a different run.");
  return snapshot;
}

// Decimal string -> BigInt all the way through formatting. Never coerce money to Number.
export function formatMoney(value: string | null, currency: string) {
  if (value === null) return "Unknown";
  if (!/^-?\d+$/.test(value)) return "Invalid amount";
  let formatter: Intl.NumberFormat;
  try {
    formatter = new Intl.NumberFormat("en-CA", { style: "currency", currency });
  } catch {
    return `${value} minor units (${currency})`;
  }
  const digits = formatter.resolvedOptions().maximumFractionDigits ?? 2;
  const amount = BigInt(value);
  const negative = amount < 0n;
  const absolute = negative ? -amount : amount;
  const scale = 10n ** BigInt(digits);
  const whole = absolute / scale;
  const fraction = String(absolute % scale).padStart(digits, "0");
  const parts = formatter.formatToParts(negative ? -whole : whole);
  let result = parts
    .map((part) => (part.type === "fraction" ? fraction : part.value))
    .join("");
  if (negative && whole === 0n) result = `−${result}`;
  return result;
}

export function parseMajorUnits(value: string, currency: string): string {
  const digits =
    new Intl.NumberFormat("en-CA", {
      style: "currency",
      currency,
    }).resolvedOptions().maximumFractionDigits ?? 2;
  const pattern = digits
    ? new RegExp(`^\\d+(?:\\.\\d{1,${digits}})?$`)
    : /^\d+$/;
  if (!pattern.test(value.trim()))
    throw new Error(
      `Enter a non-negative ${currency} amount with at most ${digits} decimal places.`,
    );
  const [whole, fraction = ""] = value.trim().split(".");
  const minor =
    BigInt(whole) * 10n ** BigInt(digits) +
    BigInt(fraction.padEnd(digits, "0") || "0");
  if (minor > 9223372036854775807n)
    throw new Error("The amount exceeds the supported ledger range.");
  return minor.toString();
}

export function openingCashPayload(input: unknown) {
  const value = z
    .object({
      amount: z.string().min(1).max(40),
      currency: z.string().regex(/^[A-Z]{3}$/),
      as_of: z.iso.date(),
      note: z.string().trim().min(3).max(2000),
      attested: z.literal(true),
    })
    .strict()
    .parse(input);
  return {
    source: "opening_snapshot",
    amount_minor: parseMajorUnits(value.amount, value.currency),
    currency: value.currency,
    as_of: value.as_of,
    note: value.note,
    attested: true,
  };
}

export function dateTime(value: unknown) {
  if (typeof value !== "string" || Number.isNaN(Date.parse(value)))
    return "Not recorded";
  return new Intl.DateTimeFormat("en-CA", {
    dateStyle: "medium",
    timeStyle: "short",
    timeZone: "America/Vancouver",
  }).format(new Date(value));
}

export function textValue(value: unknown, fallback = "Not recorded"): string {
  return typeof value === "string" ||
    typeof value === "number" ||
    typeof value === "boolean"
    ? String(value)
    : fallback;
}

export function safeEvidenceUrl(value: unknown): string | undefined {
  if (typeof value !== "string") return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function walletApprovalUrl(value: unknown): string | undefined {
  if (
    typeof value !== "string" ||
    value.length > 4096 ||
    /[\u0000-\u0020]/.test(value)
  )
    return undefined;
  try {
    const url = new URL(value);
    return url.protocol === "https:" &&
      !url.username &&
      !url.password &&
      Boolean(url.hostname)
      ? url.href
      : undefined;
  } catch {
    return undefined;
  }
}

export function displayRecord(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(displayRecord);
  if (value && typeof value === "object")
    return Object.fromEntries(
      Object.entries(value).map(([key, child]) => [
        key,
        /(?:access_token|refresh_token|id_token|api_token|secret|password|authorization|cookie|oauth_state|signed_url|download_url|^token$|^code$|^url$)/i.test(
          key,
        )
          ? "[protected]"
          : displayRecord(child),
      ]),
    );
  return value;
}
