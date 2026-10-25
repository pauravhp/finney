"use client";

import { createPatch } from "diff";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  Activity,
  ArrowDownToLine,
  ArrowRight,
  BookOpen,
  Check,
  ChevronRight,
  CircleHelp,
  ClipboardCheck,
  FileText,
  FolderOpen,
  LayoutDashboard,
  Link2,
  LoaderCircle,
  LogOut,
  Menu,
  Plus,
  RefreshCw,
  ShieldCheck,
  Sparkles,
  X,
} from "lucide-react";
import { browserSupabase } from "@/lib/supabase/browser";
import { AuthPanel } from "@/components/auth-panel";
import { PaymentExecution } from "@/components/payment-execution";
import { DirectorResponses } from "@/components/director-responses";
import {
  ArtifactDownload,
  BudgetWorkbench,
  Workbench,
} from "@/components/workbench";
import {
  ApprovalPolicy,
  paymentApprovalLabel,
} from "@/components/approval-policy";
import {
  approvalPolicyResultSchema,
  assertSnapshotScope,
  dateTime,
  displayRecord,
  formatMoney,
  openingCashPayload,
  safeEvidenceUrl,
  scopeSchema,
  snapshotSchema,
  textValue,
  type FinanceCommand,
  type FinanceSnapshot,
  type Scope,
  type ScopeChoice,
} from "@/lib/contracts";

const tabs = [
  { id: "overview", title: "Overview", icon: LayoutDashboard },
  { id: "cases", title: "Cases & evidence", icon: FolderOpen },
  { id: "approvals", title: "Approvals", icon: ClipboardCheck },
  { id: "activity", title: "Activity", icon: Activity },
  { id: "learning", title: "Learning", icon: Sparkles },
  { id: "reports", title: "Reports", icon: FileText },
  { id: "connections", title: "Connections", icon: Link2 },
] as const;
type Tab = (typeof tabs)[number]["id"];
type User = { id: string; email: string };
type StateRecord = Record<string, unknown>;

async function api<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, {
    ...init,
    cache: "no-store",
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  const body = await response.json();
  if (!response.ok)
    throw new Error(body.error ?? "The request could not be completed.");
  return body as T;
}
function Badge({
  children,
  status = "unknown",
}: {
  children?: React.ReactNode;
  status?: string;
}) {
  const tone = /failed|error|rejected|expired|offline|rolled_back/.test(status)
    ? "bad"
    : /complete|confirmed|connected|online|promoted|approved|active|healthy/.test(
          status,
        )
      ? "good"
      : /pending|review|staged|running|queued|attested/.test(status)
        ? "wait"
        : "neutral";
  return (
    <span className={`badge ${tone}`}>
      <span />
      {children ?? status.replaceAll("_", " ")}
    </span>
  );
}
function Empty({
  title,
  children,
  icon: Icon = FolderOpen,
}: {
  title: string;
  children: React.ReactNode;
  icon?: typeof FolderOpen;
}) {
  return (
    <div className="empty">
      <Icon size={25} aria-hidden="true" />
      <h3>{title}</h3>
      <p>{children}</p>
    </div>
  );
}
function RecordDetails({
  value,
  label = "Inspect record",
}: {
  value: unknown;
  label?: string;
}) {
  return (
    <details className="record-details">
      <summary>{label}</summary>
      <pre>{JSON.stringify(displayRecord(value), null, 2)}</pre>
    </details>
  );
}
function Evidence({ data }: { data: StateRecord }) {
  const values = Array.isArray(data.evidence)
    ? data.evidence
    : Array.isArray(data.sources)
      ? data.sources
      : Array.isArray(data.source_refs)
        ? data.source_refs
        : [];
  return (
    <div className="evidence">
      <h4>Source evidence</h4>
      {values.length ? (
        values.map((value, index) => {
          const row: StateRecord =
            typeof value === "object" && value !== null
              ? (value as StateRecord)
              : { reference: value };
          const url = safeEvidenceUrl(row.url ?? row.source_url);
          return (
            <div className="evidence-row" key={index}>
              <FileText size={16} aria-hidden="true" />
              <div>
                <strong>
                  {textValue(
                    row.title ??
                      row.name ??
                      row.source_id ??
                      row.id ??
                      row.reference,
                    `Source ${index + 1}`,
                  )}
                </strong>
                <span>
                  Version{" "}
                  {textValue(row.version ?? row.source_version, "unknown")}
                  {row.evidence_status
                    ? ` · ${textValue(row.evidence_status)}`
                    : ""}
                </span>
                {url && (
                  <a href={url} target="_blank" rel="noreferrer">
                    Open source <ArrowRight size={12} />
                  </a>
                )}
              </div>
            </div>
          );
        })
      ) : (
        <p className="muted">
          No source references are attached to this record yet.
        </p>
      )}
      {Array.isArray(data.attachment_statuses) &&
        data.attachment_statuses.length > 0 && (
          <div className="attachment-outcomes">
            <h4>Document extraction</h4>
            {data.attachment_statuses.map((value, index) => {
              const row = asRecord(value);
              return (
                <p key={index}>
                  <strong>
                    {textValue(row.filename, "Additional attachments")}
                  </strong>
                  <Badge status={textValue(row.extraction_status, "unknown")} />
                  {row.extraction_reason ? (
                    <span>
                      {textValue(row.extraction_reason).replaceAll("_", " ")}
                    </span>
                  ) : null}
                </p>
              );
            })}
          </div>
        )}
      <RecordDetails value={data} label="Inspect case data and provenance" />
    </div>
  );
}

export function Dashboard({
  configured,
  gmailAvailable,
  user,
}: {
  configured: boolean;
  gmailAvailable: boolean;
  user: User | null;
}) {
  const [tab, setTab] = useState<Tab>("overview");
  const [mobileMenu, setMobileMenu] = useState(false);
  const [scopes, setScopes] = useState<ScopeChoice[]>([]);
  const [scope, setScope] = useState<Scope | null>(null);
  const [snapshot, setSnapshot] = useState<FinanceSnapshot | null>(null);
  const [loading, setLoading] = useState(Boolean(configured && user));
  const [error, setError] = useState<string | null>(null);
  const [authCallbackError, setAuthCallbackError] = useState(false);
  const [notice, setNotice] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [live, setLive] = useState("Not connected");
  const [intake, setIntake] = useState("");
  const [intakeSource, setIntakeSource] = useState<"gmail" | "csv">("gmail");
  const [showIntake, setShowIntake] = useState(false);
  const [showOpening, setShowOpening] = useState(false);
  const [expanded, setExpanded] = useState<string | null>(null);
  const [resetConfirm, setResetConfirm] = useState(false);
  const [reviewed, setReviewed] = useState<Record<string, boolean>>({});
  const requestSequence = useRef(0);
  const commandKeys = useRef(new Map<string, string>());
  const scopeKey = scope ? `${scope.organization_id}:${scope.run_id}` : "";
  const currentScope = useRef(scopeKey);
  currentScope.current = scopeKey;
  const organization = scopes.find(
    (row) => row.organization_id === scope?.organization_id,
  );
  const canWork = Boolean(
    user &&
    scope &&
    snapshot &&
    !error &&
    !loading &&
    snapshot?.run.status === "active" &&
    organization?.role !== "viewer",
  );
  const canApprove =
    canWork && ["director", "approver"].includes(organization?.role ?? "");

  const loadScopes = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = await api<{ scopes: ScopeChoice[] }>(
        "/api/finance/scopes",
      );
      setScopes(result.scopes);
      const params = new URLSearchParams(window.location.search);
      const desired = scopeSchema.safeParse({
        organization_id:
          params.get("organization_id") ??
          process.env.NEXT_PUBLIC_FINANCE_ORGANIZATION_ID,
        run_id: params.get("run_id") ?? process.env.NEXT_PUBLIC_FINANCE_RUN_ID,
      });
      const allowed =
        desired.success &&
        result.scopes.some(
          (row) =>
            row.organization_id === desired.data.organization_id &&
            row.runs.some((run) => run.id === desired.data.run_id),
        );
      if (allowed && desired.success) setScope(desired.data);
      else {
        const first = result.scopes.find((row) => row.runs.length);
        setScope(
          first
            ? {
                organization_id: first.organization_id,
                run_id: first.runs[0].id,
              }
            : null,
        );
        if (desired.success)
          setNotice(
            "The requested run is unavailable to this account. Your accessible run is selected.",
          );
      }
    } catch (cause) {
      setError(
        cause instanceof Error
          ? cause.message
          : "Could not load your workspaces.",
      );
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => {
    if (configured && user) void loadScopes();
    if (new URLSearchParams(window.location.search).has("auth_error"))
      setAuthCallbackError(true);
  }, [configured, user, loadScopes]);

  const refresh = useCallback(async (selected: Scope, initial = false) => {
    const key = `${selected.organization_id}:${selected.run_id}`;
    const sequence = ++requestSequence.current;
    if (initial) setLoading(true);
    try {
      const raw = await api<unknown>(
        `/api/finance/snapshot?${new URLSearchParams(selected)}`,
      );
      const next = assertSnapshotScope(snapshotSchema.parse(raw), selected);
      if (currentScope.current !== key || sequence !== requestSequence.current)
        return;
      setSnapshot(next);
      setError(null);
    } catch (cause) {
      if (currentScope.current === key && sequence === requestSequence.current)
        setError(
          cause instanceof Error
            ? cause.message
            : "Live state could not be loaded.",
        );
    } finally {
      if (currentScope.current === key && sequence === requestSequence.current)
        setLoading(false);
    }
  }, []);

  useEffect(() => {
    setSnapshot(null);
    setShowOpening(false);
    if (!scope || !user) return;
    setExpanded(null);
    setReviewed({});
    setResetConfirm(false);
    setLive("Connecting");
    const url = new URL(window.location.href);
    url.searchParams.set("organization_id", scope.organization_id);
    url.searchParams.set("run_id", scope.run_id);
    window.history.replaceState(null, "", url);
    void refresh(scope, true);
    const client = browserSupabase();
    const channel = client.channel(
      `finance:${scope.organization_id}:${scope.run_id}`,
      { config: { private: true } },
    );
    let disposed = false;
    void client.auth.getSession().then(async ({ data }) => {
      if (disposed) return;
      await client.realtime.setAuth(data.session?.access_token);
      if (disposed) return;
      channel
        .on("broadcast", { event: "state_changed" }, () => void refresh(scope))
        .subscribe((status) => {
          if (disposed) return;
          setLive(
            status === "SUBSCRIBED"
              ? "Live"
              : status === "CLOSED"
                ? "Disconnected"
                : status === "CHANNEL_ERROR" || status === "TIMED_OUT"
                  ? "Reconnecting"
                  : "Connecting",
          );
          if (status === "SUBSCRIBED") void refresh(scope);
        });
    });
    const timer = window.setInterval(() => void refresh(scope), 30000);
    const reconnect = () => {
      if (navigator.onLine) void refresh(scope);
      else setLive("Offline");
    };
    window.addEventListener("online", reconnect);
    window.addEventListener("offline", reconnect);
    const auth = client.auth.onAuthStateChange((event, session) => {
      if (event === "SIGNED_OUT") window.location.reload();
      else if (session) void client.realtime.setAuth(session.access_token);
    });
    return () => {
      disposed = true;
      clearInterval(timer);
      window.removeEventListener("online", reconnect);
      window.removeEventListener("offline", reconnect);
      auth.data.subscription.unsubscribe();
      void client.removeChannel(channel);
    };
  }, [scope, user, refresh]);

  async function command(type: FinanceCommand, payload: StateRecord = {}) {
    if (!scope || !canWork) return false;
    const requestKey = `${scopeKey}:${type}:${JSON.stringify(payload)}`;
    const idempotencyKey =
      commandKeys.current.get(requestKey) ?? crypto.randomUUID();
    commandKeys.current.set(requestKey, idempotencyKey);
    setBusy(type);
    setNotice(null);
    try {
      const result = await api<{ job_id: string }>("/api/finance/commands", {
        method: "POST",
        body: JSON.stringify({
          ...scope,
          command_type: type,
          payload,
          idempotency_key: idempotencyKey,
        }),
      });
      commandKeys.current.delete(requestKey);
      setNotice(
        `Work queued. Job ${result.job_id}. Completion will appear in activity.`,
      );
      if (type === "intake") {
        setIntake("");
        setShowIntake(false);
      }
      await refresh(scope);
      return true;
    } catch (cause) {
      setNotice(
        cause instanceof Error ? cause.message : "The action was not accepted.",
      );
      return false;
    } finally {
      setBusy(null);
    }
  }
  async function decide(
    proposal: FinanceSnapshot["approvals"][number],
    decision: "approve" | "reject",
  ) {
    if (!scope || !canApprove) return;
    setBusy(proposal.id);
    setNotice(null);
    try {
      await api("/api/finance/approvals", {
        method: "POST",
        body: JSON.stringify({
          ...scope,
          proposal_id: proposal.id,
          expected_action_hash: proposal.action_hash,
          decision,
        }),
      });
      setNotice(
        `Your ${decision === "approve" ? "approval" : "rejection"} was recorded for this exact action.`,
      );
      setReviewed({});
      await refresh(scope);
    } catch (cause) {
      setNotice(
        cause instanceof Error
          ? cause.message
          : "The decision was not accepted.",
      );
      await refresh(scope);
    } finally {
      setBusy(null);
    }
  }
  async function changeApprovalPolicy(required: 1 | 2, revision: number) {
    if (!scope || !canWork || organization?.role !== "director")
      throw new Error(
        "Only the active event director can change payment approvals.",
      );
    setBusy("approval_policy");
    try {
      const result = approvalPolicyResultSchema.parse(
        await api<unknown>("/api/finance/approval-policy", {
          method: "POST",
          body: JSON.stringify({
            ...scope,
            required_approvals: required,
            expected_revision: revision,
          }),
        }),
      );
      if (
        result.organization_id !== scope.organization_id ||
        result.run_id !== scope.run_id ||
        result.required_payment_approvals !== required
      )
        throw new Error(
          "The finance service returned a different approval policy. Refresh to check the current setting.",
        );
      setReviewed({});
      await refresh(scope);
    } catch (cause) {
      await refresh(scope);
      throw cause;
    } finally {
      setBusy(null);
    }
  }
  async function createDemo(reset = false) {
    setBusy("demo");
    setNotice(null);
    try {
      const next = await api<Scope & { seed_status: string }>(
        "/api/finance/demo",
        {
          method: "POST",
          body: JSON.stringify({
            name: "My finance demo",
            previous_run_id: reset ? scope?.run_id : null,
          }),
        },
      );
      const url = new URL(window.location.href);
      url.searchParams.set("organization_id", next.organization_id);
      url.searchParams.set("run_id", next.run_id);
      window.history.replaceState(null, "", url);
      await loadScopes();
      setNotice(
        next.seed_status === "queued"
          ? "Your isolated demo is ready. Labeled synthetic documents are queued for real agent review; no payment or result is pre-recorded."
          : "Your isolated demo was created, but its source documents could not be queued. Use Work with Finney to add evidence while the connection is checked.",
      );
    } catch (cause) {
      setNotice(
        cause instanceof Error
          ? cause.message
          : "A demo run could not be created.",
      );
    } finally {
      setBusy(null);
      setResetConfirm(false);
    }
  }
  async function signOut() {
    try {
      await api("/auth/signout", { method: "POST", body: "{}" });
      window.location.reload();
    } catch {
      setNotice("Sign-out did not finish. Check your connection and retry.");
    }
  }
  async function connectGmail() {
    if (!scope || organization?.role !== "director" || selectedRun?.is_demo)
      return;
    setBusy("gmail");
    setNotice(null);
    try {
      const result = await api<{ authorization_url: string }>(
        "/api/connectors/gmail/start",
        { method: "POST", body: JSON.stringify(scope) },
      );
      window.location.assign(result.authorization_url);
    } catch (cause) {
      setNotice(
        cause instanceof Error
          ? cause.message
          : "Mailbox authorization could not start.",
      );
      setBusy(null);
    }
  }
  const pending =
    snapshot?.approvals.filter((row) => row.status === "pending") ?? [];
  const recentCases = snapshot?.cases ?? [];
  const selectedRun = organization?.runs.find(
    (row) => row.id === scope?.run_id,
  );

  const caseList = (limit?: number) =>
    recentCases.length ? (
      <div className="case-list">
        {recentCases.slice(0, limit).map((row) => (
          <article className="case" key={row.id}>
            <button
              className="case-heading"
              onClick={() => setExpanded(expanded === row.id ? null : row.id)}
              aria-expanded={expanded === row.id}
            >
              <span className="case-icon">
                <FolderOpen size={18} />
              </span>
              <span className="case-title">
                <strong>{row.title}</strong>
                <small>
                  Version {row.version} · Updated {dateTime(row.updated_at)}
                </small>
              </span>
              <Badge status={row.status} />
              <ChevronRight
                size={17}
                className={expanded === row.id ? "rotated" : ""}
              />
            </button>
            {expanded === row.id && (
              <div className="case-body">
                <DirectorResponses responses={row.data.director_responses} />
                <Evidence data={row.data} />
                <button
                  disabled={!canWork || Boolean(busy)}
                  onClick={() =>
                    command("review_case", {
                      case_id: row.id,
                      expected_version: row.version,
                    })
                  }
                >
                  Request review
                </button>
              </div>
            )}
          </article>
        ))}
      </div>
    ) : (
      <Empty title="No financial cases yet">
        Intake or import source records to start a source-linked case. Activity
        appears here when the worker persists it.
      </Empty>
    );
  const activityList = (limit?: number) =>
    snapshot?.activity.length ? (
      <ol className="activity-list">
        {snapshot.activity.slice(0, limit).map((row) => (
          <li key={row.id}>
            <span className="event-dot" />
            <div>
              <strong>{row.event_type.replaceAll("_", " ")}</strong>
              <time>{dateTime(row.created_at)}</time>
              <RecordDetails
                value={row.payload}
                label="Inspect event evidence"
              />
            </div>
          </li>
        ))}
      </ol>
    ) : (
      <Empty title="Waiting for real activity" icon={Activity}>
        Recorded intake, reviews, decisions, and execution events will appear
        here. No execution has been inferred.
      </Empty>
    );

  return (
    <div className="app-shell">
      <a className="skip-link" href="#main">
        Skip to finance workspace
      </a>
      <aside className={`sidebar ${mobileMenu ? "is-open" : ""}`}>
        <a className="brand" href="/" aria-label="Director Finance home">
          <span className="brand-mark">
            <Sparkles size={23} strokeWidth={1.6} />
          </span>
          <span>
            Director<span className="brand-subtitle">Finance workspace</span>
          </span>
        </a>
        <button
          className="mobile-close icon-button"
          onClick={() => setMobileMenu(false)}
          aria-label="Close navigation"
        >
          <X size={20} />
        </button>
        <div className="workspace-label">
          {snapshot?.organization.name ?? "Your event"}
          <span>
            {selectedRun?.is_demo ? "Isolated demo run" : "Finance operations"}
          </span>
        </div>
        <nav aria-label="Workspace">
          {tabs.map(({ id, title, icon: Icon }) => (
            <button
              key={id}
              className={`nav-item ${tab === id ? "selected" : ""}`}
              aria-current={tab === id ? "page" : undefined}
              onClick={() => {
                setTab(id);
                setMobileMenu(false);
              }}
            >
              <Icon size={18} strokeWidth={1.7} />
              <span>{title}</span>
              {id === "approvals" && pending.length > 0 && (
                <span className="nav-count">{pending.length}</span>
              )}
            </button>
          ))}
        </nav>
        <div className="sidebar-bottom">
          <div className="authority-note">
            <ShieldCheck size={17} />
            <p>
              Your team holds authority.
              <span>Agent work stays inspectable.</span>
            </p>
          </div>
          {user ? (
            <>
              <div className="member">
                <span className="avatar">
                  {user.email.slice(0, 1).toUpperCase()}
                </span>
                <span className="member-info">
                  <strong>{user.email}</strong>
                  <small>{organization?.role ?? "Signed in"}</small>
                </span>
                <button
                  className="icon-button"
                  onClick={signOut}
                  aria-label="Sign out"
                >
                  <LogOut size={16} />
                </button>
              </div>
            </>
          ) : (
            <span className="sidebar-footnote">
              Event-owned data. Source-backed decisions.
            </span>
          )}
        </div>
      </aside>
      <div className="workspace">
        <header className="topbar">
          <button
            className="mobile-menu icon-button"
            aria-label="Open navigation"
            onClick={() => setMobileMenu(true)}
          >
            <Menu size={21} />
          </button>
          <div className="breadcrumb">
            Finance <ChevronRight size={14} />
            <strong>{tabs.find((row) => row.id === tab)?.title}</strong>
          </div>
          <div className="topbar-right">
            <span
              className={`live-state ${live === "Live" ? "connected" : ""}`}
            >
              <span />
              {live}
            </span>
            {user && (
              <button
                className="icon-button"
                disabled={!scope || loading}
                onClick={() => scope && refresh(scope, true)}
                aria-label="Refresh financial state"
              >
                <RefreshCw size={16} className={loading ? "spin" : ""} />
              </button>
            )}
          </div>
        </header>
        <main id="main">
          <div className="page-heading">
            <div>
              <h1>
                {tab === "overview"
                  ? "A clear view of your finances."
                  : tabs.find((row) => row.id === tab)?.title}
              </h1>
              <p>
                {tab === "overview"
                  ? "Know what is confirmed, what is committed, and what needs your decision."
                  : tab === "learning"
                    ? "From observed behavior to evaluated procedure changes. Every result stays inspectable."
                    : tab === "approvals"
                      ? "Review the exact action. Decisions are bound to its current version."
                      : tab === "connections"
                        ? "Real provider access and worker health, with clear ownership."
                        : "Source-linked records for your event and selected run."}
              </p>
            </div>
            {user && (
              <button
                className="primary"
                disabled={!canWork || Boolean(busy)}
                onClick={() => setShowIntake(!showIntake)}
              >
                <Plus size={16} /> Add source records
              </button>
            )}
          </div>
          {!configured && (
            <section className="setup-banner">
              <span className="setup-symbol">
                <Sparkles size={27} />
              </span>
              <div>
                <h2>Connect your event to begin</h2>
                <p>
                  This workspace needs its Supabase connection. Add the public
                  project URL and publishable key, apply the finance migrations,
                  and enable email sign-in in Supabase Auth.
                </p>
                <a
                  href="https://supabase.com/docs/guides/auth/passwords"
                  target="_blank"
                  rel="noreferrer"
                >
                  Email sign-in setup <ArrowRight size={14} />
                </a>
                <p className="setup-footnote">
                  The director connects the event Gmail mailbox separately. Team
                  members sign in with their email and password.
                </p>
              </div>
              <Badge status="unknown">Setup required</Badge>
            </section>
          )}
          {configured && !user && (
            <AuthPanel
              key={String(authCallbackError)}
              callbackError={authCallbackError}
            />
          )}
          {user && scopes.length > 0 && (
            <div className="scope-bar">
              <label>
                Event
                <select
                  value={scope?.organization_id ?? ""}
                  onChange={(event) => {
                    const org = scopes.find(
                      (row) => row.organization_id === event.target.value,
                    );
                    setScope(
                      org?.runs[0]
                        ? {
                            organization_id: org.organization_id,
                            run_id: org.runs[0].id,
                          }
                        : null,
                    );
                  }}
                >
                  {scopes.map((row) => (
                    <option
                      key={row.organization_id}
                      value={row.organization_id}
                    >
                      {row.organization_name}
                    </option>
                  ))}
                </select>
              </label>
              <label>
                Run
                <select
                  value={scope?.run_id ?? ""}
                  onChange={(event) =>
                    scope && setScope({ ...scope, run_id: event.target.value })
                  }
                >
                  {organization?.runs.map((row) => (
                    <option key={row.id} value={row.id}>
                      {row.name}
                      {row.is_demo ? " · Demo" : ""}
                    </option>
                  ))}
                </select>
              </label>
              <span>
                {selectedRun?.is_demo
                  ? "Private to your demo session"
                  : "Shared with authorized event members"}
              </span>
            </div>
          )}
          {error && (
            <div className="message error-message" role="alert">
              <CircleHelp size={19} />
              <div>
                <strong>
                  {snapshot
                    ? "Showing the last received state"
                    : "Finance is unavailable"}
                </strong>
                <p>{error}</p>
              </div>
              {user && (
                <button
                  onClick={() => (scope ? refresh(scope, true) : loadScopes())}
                >
                  Retry
                </button>
              )}
            </div>
          )}
          {notice && (
            <div className="message" role="status">
              <Check size={18} />
              <p>{notice}</p>
              <button
                className="icon-button"
                onClick={() => setNotice(null)}
                aria-label="Dismiss message"
              >
                <X size={17} />
              </button>
            </div>
          )}
          {user && !loading && !scopes.length && !error && (
            <Empty title="No event access yet" icon={ShieldCheck}>
              You are signed in. An event director can add your membership. You
              can also create a private, empty demo run to explore the workflow.
              <button
                className="primary"
                disabled={Boolean(busy)}
                onClick={() => createDemo()}
              >
                Create my demo run
              </button>
            </Empty>
          )}
          {user && !loading && scopes.length > 0 && !scope && !error && (
            <Empty title="No finance run exists yet" icon={FolderOpen}>
              Initialize a shared event run through onboarding, or create your
              own empty demo.
              <button
                className="primary"
                disabled={Boolean(busy)}
                onClick={() => createDemo()}
              >
                Create my demo run
              </button>
            </Empty>
          )}
          {user && scope && selectedRun?.is_demo && (
            <div className="demo-tools">
              <span>
                This demo is private to your account. Resetting cancels only
                this run's queued work. Two-person payments require a shared
                event run.
              </span>
              {resetConfirm ? (
                <>
                  <button
                    disabled={Boolean(busy)}
                    onClick={() => setResetConfirm(false)}
                  >
                    Keep current run
                  </button>
                  <button
                    disabled={Boolean(busy)}
                    onClick={() => createDemo(true)}
                  >
                    Confirm new empty run
                  </button>
                </>
              ) : (
                <button
                  disabled={Boolean(busy)}
                  onClick={() => setResetConfirm(true)}
                >
                  Start fresh demo
                </button>
              )}
            </div>
          )}
          {showIntake && (
            <form
              className="intake-form"
              onSubmit={(event) => {
                event.preventDefault();
                if (intakeSource === "gmail" || intake.trim())
                  void command(
                    "intake",
                    intakeSource === "gmail"
                      ? { source: "gmail" }
                      : {
                          source: "csv",
                          content: intake,
                          currency: snapshot?.run.currency,
                        },
                  );
              }}
            >
              <label htmlFor="intake-source">Add source records</label>
              <select
                id="intake-source"
                value={intakeSource}
                onChange={(event) =>
                  setIntakeSource(event.target.value as "gmail" | "csv")
                }
              >
                <option value="gmail">
                  Sync connected Gmail director-finance label
                </option>
                <option value="csv">
                  Import CSV records ({snapshot?.run.currency ?? "run currency"}
                  )
                </option>
              </select>
              {intakeSource === "csv" ? (
                <>
                  <label htmlFor="intake">CSV content</label>
                  <textarea
                    id="intake"
                    required
                    maxLength={1000000}
                    rows={6}
                    value={intake}
                    onChange={(event) => setIntake(event.target.value)}
                    placeholder="reference,date,description,amount,kind"
                  />
                  <p>
                    Required columns: reference, date, description, amount,
                    kind. Records remain reported evidence; an opening_balance
                    row does not establish cash.
                  </p>
                </>
              ) : (
                <p>
                  Sync only the director-finance label configured by your
                  director. New source versions become cases and queued reviews.
                  A connected director mailbox is required.
                </p>
              )}
              <p>
                Source documents are evidence. Financial policy and payment
                authority remain controlled by your team.
              </p>
              <div>
                <button type="button" onClick={() => setShowIntake(false)}>
                  Cancel
                </button>
                <button
                  className="primary"
                  disabled={
                    !canWork ||
                    Boolean(busy) ||
                    (intakeSource === "csv" && !intake.trim())
                  }
                  type="submit"
                >
                  {busy === "intake"
                    ? "Queuing…"
                    : intakeSource === "gmail"
                      ? "Queue mailbox sync"
                      : "Queue CSV import"}
                  <ArrowRight size={15} />
                </button>
              </div>
            </form>
          )}
          {loading && !snapshot && (
            <div className="loading" role="status">
              <LoaderCircle size={19} className="spin" />
              Loading authorized financial state…
            </div>
          )}
          {tab === "overview" && (
            <>
              <section className="position-section">
                <div className="section-heading">
                  <h2>Financial position</h2>
                  <div className="position-actions">
                    <Badge
                      status={snapshot?.position.evidence_status ?? "unknown"}
                    />
                    {snapshot &&
                      snapshot.position.cash_minor === null &&
                      organization?.role === "director" &&
                      !selectedRun?.is_demo && (
                        <button
                          className="text-button"
                          disabled={!canWork || Boolean(busy)}
                          onClick={() => setShowOpening(!showOpening)}
                        >
                          Set opening cash
                        </button>
                      )}
                  </div>
                </div>
                <div className="position-grid">
                  {[
                    ["Recorded cash", "cash_minor"],
                    ["Committed", "committed_minor"],
                    ["Receivable", "receivable_minor"],
                    ["Available", "available_minor"],
                  ].map(([label, field]) => (
                    <div key={field}>
                      <span>{label}</span>
                      <strong>
                        {formatMoney(
                          snapshot?.position[field as "cash_minor"] ?? null,
                          snapshot?.position.currency ?? "USD",
                        )}
                      </strong>
                    </div>
                  ))}
                </div>
                <div className="position-footer">
                  <span>
                    Reconciliation cutoff:{" "}
                    {dateTime(snapshot?.position.reconciled_at)}
                  </span>
                  <button
                    className="text-button"
                    disabled={!canWork || Boolean(busy)}
                    onClick={() => command("refresh_forecast")}
                  >
                    Refresh forecast <RefreshCw size={13} />
                  </button>
                </div>
              </section>
              {showOpening &&
                snapshot &&
                organization?.role === "director" &&
                !selectedRun?.is_demo &&
                snapshot.position.cash_minor === null && (
                  <OpeningCashForm
                    currency={snapshot.position.currency}
                    busy={Boolean(busy)}
                    onCancel={() => setShowOpening(false)}
                    onSubmit={async (payload) => {
                      const accepted = await command("intake", payload);
                      if (accepted) setShowOpening(false);
                      return accepted;
                    }}
                  />
                )}
              {scope && snapshot && (
                <>
                  <Workbench
                    key={`workbench:${scopeKey}`}
                    scope={scope}
                    currency={snapshot.run.currency}
                    cases={snapshot.cases}
                    canEdit={
                      canWork &&
                      ["director", "finance"].includes(organization?.role ?? "")
                    }
                    busy={Boolean(busy)}
                    onCommand={command}
                    onRefresh={() => refresh(scope)}
                  />
                  <BudgetWorkbench
                    key={`budget:${scopeKey}`}
                    scope={scope}
                    currency={snapshot.run.currency}
                    budget={snapshot.budget}
                    canEdit={
                      canWork &&
                      !busy &&
                      ["director", "finance"].includes(organization?.role ?? "")
                    }
                    canDecide={
                      canWork && !busy && organization?.role === "director"
                    }
                    onRefresh={() => refresh(scope)}
                  />
                </>
              )}
              <Obligations snapshot={snapshot} />
              <div className="overview-grid">
                <section>
                  <div className="section-heading">
                    <h2>Work in focus</h2>
                    <button
                      className="text-button"
                      onClick={() => setTab("cases")}
                    >
                      All cases <ArrowRight size={14} />
                    </button>
                  </div>
                  {caseList(5)}
                </section>
                <section className="decision-panel">
                  <ClipboardCheck size={23} strokeWidth={1.6} />
                  <h2>
                    {pending.length
                      ? `${pending.length} decision${pending.length === 1 ? "" : "s"} waiting`
                      : "No decisions waiting"}
                  </h2>
                  <p>
                    {pending.length
                      ? "Review destinations, amounts, and evidence before recording your decision."
                      : "Proposals appear here when the agent prepares an action for your team."}
                  </p>
                  <button
                    disabled={!pending.length}
                    onClick={() => setTab("approvals")}
                  >
                    Review approvals <ArrowRight size={15} />
                  </button>
                  <div className="decision-note">
                    <ShieldCheck size={16} />
                    {snapshot
                      ? `Payments: ${paymentApprovalLabel(snapshot.run.required_payment_approvals)}.`
                      : "Payment approval policy awaits event state."}
                  </div>
                </section>
              </div>
              <section>
                <div className="section-heading">
                  <h2>Recent activity</h2>
                  <button
                    className="text-button"
                    onClick={() => setTab("activity")}
                  >
                    Full history <ArrowRight size={14} />
                  </button>
                </div>
                {activityList(4)}
              </section>
            </>
          )}
          {tab === "cases" && (
            <section>
              {scope && snapshot && (
                <Workbench
                  key={`cases-workbench:${scopeKey}`}
                  scope={scope}
                  currency={snapshot.run.currency}
                  cases={snapshot.cases}
                  canEdit={
                    canWork &&
                    ["director", "finance"].includes(organization?.role ?? "")
                  }
                  busy={Boolean(busy)}
                  onCommand={command}
                  onRefresh={() => refresh(scope)}
                />
              )}
              {caseList()}
              <SourceRegister snapshot={snapshot} />
            </section>
          )}
          {tab === "approvals" && (
            <section>
              {snapshot && (
                <ApprovalPolicy
                  key={`${snapshot.organization.id}:${snapshot.run.id}`}
                  run={snapshot.run}
                  canEdit={canWork && organization?.role === "director"}
                  busy={Boolean(busy)}
                  onSave={changeApprovalPolicy}
                />
              )}
              {snapshot?.approvals.length ? (
                <div className="proposal-list">
                  {snapshot.approvals.map((proposal) => {
                    const canDecide =
                      canApprove &&
                      (proposal.required_approvals !== 1 ||
                        organization?.role === "director");
                    const alreadyDecided = proposal.decisions.some(
                      (row) =>
                        row.user_id === user?.id ||
                        row.actor_user_id === user?.id,
                    );
                    const expired = Boolean(
                      proposal.expires_at &&
                      Date.parse(proposal.expires_at) <= Date.now(),
                    );
                    return (
                      <article className="proposal" key={proposal.id}>
                        <div className="section-heading">
                          <h2>
                            {textValue(
                              proposal.action.title ??
                                proposal.action.type ??
                                proposal.action.action_type,
                              "Proposed financial action",
                            )}
                          </h2>
                          <Badge
                            status={expired ? "expired" : proposal.status}
                          />
                        </div>
                        <dl className="action-facts">
                          {[
                            "destination",
                            "asset",
                            "network",
                            "amount_minor",
                            "amount_base_units",
                            "currency",
                            "case_id",
                          ]
                            .filter((key) => proposal.action[key] !== undefined)
                            .map((key) => (
                              <div key={key}>
                                <dt>{key.replaceAll("_", " ")}</dt>
                                <dd>{textValue(proposal.action[key])}</dd>
                              </div>
                            ))}
                        </dl>
                        <RecordDetails
                          value={proposal.action}
                          label="Inspect complete exact action"
                        />
                        <div className="proposal-meta">
                          <span>
                            {proposal.approval_count} of{" "}
                            {proposal.required_approvals} approvals
                          </span>
                          <span>Expires {dateTime(proposal.expires_at)}</span>
                        </div>
                        <p className="hash">
                          Action hash <code>{proposal.action_hash}</code>
                        </p>
                        {proposal.decisions.length > 0 && (
                          <RecordDetails
                            value={proposal.decisions}
                            label="Inspect recorded human decisions"
                          />
                        )}
                        {proposal.status === "pending" && !expired && (
                          <>
                            <label className="review-check">
                              <input
                                type="checkbox"
                                checked={Boolean(reviewed[proposal.id])}
                                onChange={(event) =>
                                  setReviewed({
                                    ...reviewed,
                                    [proposal.id]: event.target.checked,
                                  })
                                }
                                disabled={!canDecide || alreadyDecided}
                              />
                              I reviewed this exact action and its source
                              evidence.
                            </label>
                            <div className="proposal-actions">
                              <button
                                disabled={
                                  !canDecide || Boolean(busy) || alreadyDecided
                                }
                                onClick={() => decide(proposal, "reject")}
                              >
                                Reject action
                              </button>
                              <button
                                className="primary"
                                disabled={
                                  !canDecide ||
                                  !reviewed[proposal.id] ||
                                  Boolean(busy) ||
                                  alreadyDecided
                                }
                                onClick={() => decide(proposal, "approve")}
                              >
                                <Check size={16} />
                                {alreadyDecided
                                  ? "Decision recorded"
                                  : "Approve exact action"}
                              </button>
                            </div>
                            {!canDecide && (
                              <p className="muted">
                                {proposal.required_approvals === 1
                                  ? "The event director must make this decision under the director-only policy."
                                  : "A director or designated approver must make this decision."}
                              </p>
                            )}
                          </>
                        )}
                        <PaymentExecution
                          proposal={proposal}
                          payments={snapshot.payments}
                          jobs={snapshot.payment_jobs}
                          canOperate={
                            canApprove &&
                            (proposal.required_approvals !== 1 ||
                              organization?.role === "director")
                          }
                          isDemo={Boolean(selectedRun?.is_demo)}
                          busy={Boolean(busy)}
                          onExecute={(proposalId) =>
                            command("execute_payment", {
                              proposal_id: proposalId,
                            })
                          }
                        />
                      </article>
                    );
                  })}
                </div>
              ) : (
                <Empty title="No proposals to approve" icon={ClipboardCheck}>
                  The agent must prepare a versioned action before anyone can
                  approve it.{" "}
                  {snapshot
                    ? `Payments require ${snapshot.run.required_payment_approvals === 1 ? "the event director’s approval" : "two distinct eligible people’s approvals"}.`
                    : "The event’s approval policy appears when financial state is available."}
                </Empty>
              )}
            </section>
          )}
          {tab === "activity" && <section>{activityList()}</section>}
          {tab === "learning" && (
            <Learning
              snapshot={snapshot}
              canWork={canWork && !busy}
              onEvaluate={(payload) => command("evaluate_improvement", payload)}
            />
          )}
          {tab === "reports" && (
            <Reports
              snapshot={snapshot}
              canWork={canWork && !busy}
              onGenerate={() =>
                command("generate_report", { report_type: "finance_summary" })
              }
            />
          )}
          {tab === "connections" && (
            <Connections
              snapshot={snapshot}
              role={organization?.role}
              configured={configured}
              gmailAvailable={gmailAvailable}
              isDemo={Boolean(selectedRun?.is_demo)}
              busy={Boolean(busy)}
              onConnectGmail={connectGmail}
            />
          )}
          <footer className="workspace-footer">
            <span>
              <ShieldCheck size={13} />
              {snapshot
                ? `${snapshot.run.name} · revision ${snapshot.run.revision}`
                : "Awaiting connected event records"}
            </span>
            <span>Updated {dateTime(snapshot?.updated_at)} · Pacific time</span>
          </footer>
        </main>
      </div>
    </div>
  );
}

function asRecord(value: unknown): StateRecord {
  return value && typeof value === "object" && !Array.isArray(value)
    ? (value as StateRecord)
    : {};
}
function generation(row: StateRecord) {
  return asRecord(asRecord(asRecord(row.metadata).generation).output);
}
function Procedure({
  row,
  baseline,
  scope,
}: {
  row: StateRecord;
  baseline?: StateRecord;
  scope: Scope;
}) {
  const [artifact, setArtifact] = useState<string | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [fetching, setFetching] = useState(false);
  const candidate = textValue(generation(row).procedure, "");
  const prior = baseline ? textValue(generation(baseline).procedure, "") : "";
  async function inspectArtifact() {
    const path = textValue(row.artifact_path, "");
    if (!path.startsWith(`${scope.organization_id}/${scope.run_id}/`)) {
      setFailure("The artifact path does not belong to this run.");
      return;
    }
    setFetching(true);
    setFailure(null);
    try {
      const { data, error } = await browserSupabase()
        .storage.from("finance-artifacts")
        .download(path);
      if (error || !data)
        throw new Error("The private artifact is unavailable to this account.");
      if (data.size > 1048576)
        throw new Error(
          "This artifact is too large to inspect inline. Use the authorized export tool.",
        );
      setArtifact(await data.text());
    } catch (cause) {
      setFailure(
        cause instanceof Error
          ? cause.message
          : "The artifact could not be read.",
      );
    } finally {
      setFetching(false);
    }
  }
  return (
    <div>
      {Boolean(generation(row).rationale) && (
        <p>{textValue(generation(row).rationale)}</p>
      )}
      {candidate && prior ? (
        <details className="record-details">
          <summary>Inspect procedure diff</summary>
          <pre>
            {createPatch(
              textValue(row.skill_name, "procedure"),
              prior,
              candidate,
              "baseline",
              "candidate",
            )}
          </pre>
          <div className="procedure-comparison">
            <div>
              <h4>Baseline</h4>
              <pre>{prior}</pre>
            </div>
            <div>
              <h4>Candidate</h4>
              <pre>{candidate}</pre>
            </div>
          </div>
        </details>
      ) : candidate ? (
        <details className="record-details">
          <summary>Inspect candidate procedure</summary>
          <pre>{candidate}</pre>
        </details>
      ) : (
        <p className="muted">
          Procedure text must be read from the stored artifact.
        </p>
      )}
      {Boolean(row.artifact_path) && (
        <button onClick={inspectArtifact} disabled={fetching}>
          {fetching
            ? "Reading artifact…"
            : "Inspect private procedure artifact"}
        </button>
      )}
      {failure && <p role="alert">{failure}</p>}
      {artifact !== null && <pre className="diff">{artifact}</pre>}
    </div>
  );
}
function Learning({
  snapshot,
  canWork,
  onEvaluate,
}: {
  snapshot: FinanceSnapshot | null;
  canWork: boolean;
  onEvaluate: (payload: StateRecord) => void;
}) {
  const [traceId, setTraceId] = useState("");
  const [suiteId, setSuiteId] = useState("organizer-expenses-split-payment-v5");
  const improvement = snapshot?.improvements;
  const diagnoses =
    improvement?.trace_events.filter(
      (row) => row.event_type === "improvement_diagnosed",
    ) ?? [];
  const actorTraces =
    improvement?.trace_events.filter(
      (row) => row.event_type === "actor_completed",
    ) ?? [];
  const results = new Map<
    string,
    { baseline?: StateRecord; candidate?: StateRecord }
  >();
  for (const row of improvement?.eval_results ?? []) {
    const key = `${textValue(row.eval_run_id)}:${textValue(row.case_key)}`;
    const pair = results.get(key) ?? {};
    if (row.variant === "baseline" || row.variant === "candidate")
      pair[row.variant] = row;
    results.set(key, pair);
  }
  const pass = (row?: StateRecord) =>
    row ? (
      <>
        <Badge status={row.passed === true ? "confirmed" : "failed"}>
          {row.passed === true ? "Passed" : "Failed"}
        </Badge>
        <span className="eval-invariants">
          Controls: {row.hard_invariants_passed === true ? "passed" : "failed"}
        </span>
        <RecordDetails
          value={{ metrics: row.metrics, details: row.details }}
          label="Inspect measurement"
        />
      </>
    ) : (
      <span className="muted">Not measured</span>
    );
  return (
    <div className="learning">
      <section className="learning-intro">
        <BookOpen size={23} />
        <div>
          <h2>Improvement needs evidence</h2>
          <p>
            Diagnosis, procedure changes, paired evaluation, and promotion are
            recorded separately. Evaluation runs disable financial side effects.
          </p>
        </div>
        <Badge status="unknown">Controls stay fixed</Badge>
      </section>
      <section>
        <div className="section-heading">
          <h2>Review jobs</h2>
        </div>
        <p className="muted">
          A completed review can reject a change. Only the measured evaluations
          and promotion records below establish improvement.
        </p>
        {snapshot?.jobs
          .filter((job) => job.command_type === "evaluate_improvement")
          .map((job) => (
            <article className="learning-record" key={textValue(job.id)}>
              <div className="section-heading">
                <span>
                  Automatic or requested review · {dateTime(job.created_at)}
                </span>
                <Badge status={textValue(job.status)} />
              </div>
              {Boolean(job.error_code) && (
                <p role="alert">
                  Review needs attention: {textValue(job.error_code)}
                </p>
              )}
            </article>
          ))}
      </section>
      <section>
        <div className="section-heading">
          <h2>Observed diagnosis</h2>
        </div>
        {diagnoses.length ? (
          diagnoses.map((row, index) => {
            const output = asRecord(asRecord(row.payload).output);
            return (
              <article
                className="learning-record"
                key={textValue(row.id, String(index))}
              >
                <h3>{textValue(output.issue_type, "Observed behavior")}</h3>
                <p>{textValue(output.diagnosis)}</p>
                <p>Desired behavior: {textValue(output.desired_behavior)}</p>
                <RecordDetails
                  value={row}
                  label="Inspect diagnosis and source trace references"
                />
              </article>
            );
          })
        ) : (
          <p className="muted">
            No diagnosis has been recorded from a real trace.
          </p>
        )}
      </section>
      <section>
        <div className="section-heading">
          <h2>Procedure versions</h2>
        </div>
        {improvement?.skill_versions.length && snapshot ? (
          improvement.skill_versions.map((row, index) => (
            <article
              className="learning-record"
              key={textValue(row.id, String(index))}
            >
              <div className="section-heading">
                <h3>
                  {textValue(row.skill_name, "Finance procedure")} ·{" "}
                  {textValue(row.version, "Unversioned")}
                </h3>
                <Badge status={textValue(row.status, "candidate")} />
              </div>
              <Procedure
                row={row}
                baseline={improvement.skill_versions.find(
                  (prior) => prior.id === row.parent_version_id,
                )}
                scope={{
                  organization_id: snapshot.organization.id,
                  run_id: snapshot.run.id,
                }}
              />
              <RecordDetails
                value={row}
                label="Inspect version, lineage, and generation evidence"
              />
            </article>
          ))
        ) : (
          <Empty title="No learned procedure yet" icon={Sparkles}>
            A real observed trace must produce a diagnosis and candidate change.
            No improvement is assumed from a judge score alone.
          </Empty>
        )}
      </section>
      <section>
        <div className="section-heading">
          <h2>Paired evaluation</h2>
        </div>
        {canWork && (
          <form
            className="evaluation-form"
            onSubmit={(event) => {
              event.preventDefault();
              onEvaluate({ trace_id: traceId, suite_id: suiteId.trim() });
            }}
          >
            <label>
              Observed trace
              <select
                required
                value={traceId}
                onChange={(event) => setTraceId(event.target.value)}
              >
                <option value="">Select a completed actor trace</option>
                {actorTraces.map((row) => (
                  <option key={textValue(row.id)} value={textValue(row.id)}>
                    {dateTime(row.created_at)} · {textValue(row.id)}
                  </option>
                ))}
              </select>
            </label>
            <label>
              Trusted evaluation suite
              <input
                required
                maxLength={200}
                value={suiteId}
                onChange={(event) => setSuiteId(event.target.value)}
                placeholder="Independently reviewed suite ID"
              />
            </label>
            <button disabled={!traceId || !suiteId.trim()}>
              Queue evaluation <ArrowRight size={14} />
            </button>
            <p>
              The default suite uses labeled synthetic test-organization inputs
              with real model replay. The worker validates independently
              reviewed expectations; missing suites are blocked.
            </p>
          </form>
        )}
        {improvement?.eval_runs.length ? (
          improvement.eval_runs.map((row, index) => (
            <div
              className="learning-record"
              key={textValue(row.id, String(index))}
            >
              <div className="section-heading">
                <h3>
                  {textValue(row.skill_name, "Finance")} evaluation ·{" "}
                  {textValue(row.id)}
                </h3>
                <Badge status={textValue(row.status, "unknown")} />
              </div>
              <RecordDetails
                value={row}
                label="Inspect evaluation design, sample count, and overhead"
              />
            </div>
          ))
        ) : (
          <p className="muted">No evaluation runs have been recorded.</p>
        )}
        {results.size ? (
          <div className="table-scroll">
            <table>
              <caption>Actual per-case evaluation results</caption>
              <thead>
                <tr>
                  <th>Case</th>
                  <th>Baseline</th>
                  <th>Candidate</th>
                </tr>
              </thead>
              <tbody>
                {Array.from(results.entries()).map(([key, pair]) => (
                  <tr key={key}>
                    <td>
                      {textValue((pair.baseline ?? pair.candidate)?.case_key)}
                      <span className="eval-invariants">
                        {textValue(
                          asRecord((pair.baseline ?? pair.candidate)?.details)
                            .group,
                          "Group unknown",
                        )}
                      </span>
                    </td>
                    <td>{pass(pair.baseline)}</td>
                    <td>{pass(pair.candidate)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : null}
      </section>
      <section>
        <div className="section-heading">
          <h2>Promotion & rollback</h2>
        </div>
        {improvement?.promotions.length ? (
          improvement.promotions.map((row, index) => (
            <div
              className="learning-record"
              key={textValue(row.id, String(index))}
            >
              <Badge status={textValue(row.state, "unknown")} />
              <p>{textValue(row.reason)}</p>
              <RecordDetails
                value={row}
                label="Inspect promotion gate, scope, and rollback evidence"
              />
            </div>
          ))
        ) : (
          <p className="muted">
            No candidate has a recorded promotion. Financial policy and approval
            rules remain outside the improver's authority.
          </p>
        )}
      </section>
    </div>
  );
}
function Reports({
  snapshot,
  canWork,
  onGenerate,
}: {
  snapshot: FinanceSnapshot | null;
  canWork: boolean;
  onGenerate: () => void;
}) {
  const [failure, setFailure] = useState<string | null>(null);
  const [downloading, setDownloading] = useState<string | null>(null);
  async function download(row: StateRecord) {
    if (!snapshot) return;
    const path = textValue(row.artifact_path, "");
    if (!path.startsWith(`${snapshot.organization.id}/${snapshot.run.id}/`)) {
      setFailure("The report artifact does not belong to this run.");
      return;
    }
    setDownloading(textValue(row.id));
    setFailure(null);
    try {
      const { data, error } = await browserSupabase()
        .storage.from("finance-artifacts")
        .download(path);
      if (error || !data)
        throw new Error("The private report is unavailable to this account.");
      const url = URL.createObjectURL(
        new Blob([data], { type: "application/octet-stream" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `finance-report-${textValue(row.id)}.json`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setFailure(
        cause instanceof Error
          ? cause.message
          : "The report could not be downloaded.",
      );
    } finally {
      setDownloading(null);
    }
  }
  return (
    <section>
      <div className="section-heading">
        <h2>Source-linked financial reports</h2>
        <button disabled={!canWork} onClick={onGenerate}>
          <FileText size={15} />
          Generate report
        </button>
      </div>
      <p className="section-description">
        Reports distinguish confirmed balances, owner-attested records, pending
        obligations, and unknowns. Private artifacts require authorized access.
      </p>
      {failure && (
        <p role="alert" className="section-description">
          {failure}
        </p>
      )}
      {snapshot?.reports.length ? (
        snapshot.reports.map((row, index) => (
          <article
            className="report-row"
            key={textValue(row.id, String(index))}
          >
            <FileText size={21} />
            <div>
              <h3>
                {textValue(asRecord(row.data).title, "Financial summary")}
              </h3>
              <p>
                Created {dateTime(row.created_at)} · Cutoff{" "}
                {dateTime(row.cutoff)}
              </p>
              <RecordDetails
                value={row.data}
                label="Inspect report figures and provenance"
              />
            </div>
            {Boolean(row.artifact_path) ? (
              <button
                disabled={Boolean(downloading)}
                onClick={() => download(row)}
              >
                <ArrowDownToLine size={15} />
                {downloading === textValue(row.id)
                  ? "Downloading…"
                  : "Download report"}
              </button>
            ) : (
              <Badge status="unknown">Export pending</Badge>
            )}
          </article>
        ))
      ) : (
        <Empty title="No report has been generated" icon={FileText}>
          Generate a report from the selected run's actual records. A queued
          request appears in activity before a completed report is available.
        </Empty>
      )}
    </section>
  );
}
function Connections({
  snapshot,
  role,
  configured,
  gmailAvailable,
  isDemo,
  busy,
  onConnectGmail,
}: {
  snapshot: FinanceSnapshot | null;
  role?: string;
  configured: boolean;
  gmailAvailable: boolean;
  isDemo: boolean;
  busy: boolean;
  onConnectGmail: () => void;
}) {
  return (
    <div>
      <section className="connection-owner">
        <ShieldCheck size={23} />
        <div>
          <h2>One mailbox, clear ownership</h2>
          <p>
            The director connects the shared event Gmail mailbox. Finance
            members and approvers sign in with their email and password.
          </p>
          <span>
            {role === "director"
              ? isDemo
                ? "Personal demo runs do not connect a mailbox. Use a shared event run for director-authorized Gmail intake."
                : gmailAvailable
                  ? "Connect the mailbox selected for this event. Intake is limited to the configured finance label or test thread."
                  : "The event owner connects Gmail once through Hermes on the worker host. This dashboard then shows the connection and imported finance records."
              : "Ask your event director to connect or replace the mailbox."}
          </span>
          {role === "director" && !isDemo && gmailAvailable && (
            <button
              className="gmail-connect"
              disabled={!gmailAvailable || busy || !snapshot}
              onClick={onConnectGmail}
            >
              <Link2 size={14} />
              Connect event Gmail
            </button>
          )}
          {role === "director" && !isDemo && !gmailAvailable && (
            <p>
              Owner setup: follow the README’s Gmail step and run{" "}
              <code>finance gmail-connect</code>.
            </p>
          )}
        </div>
      </section>
      <div className="health-list">
        <div className="health-row">
          <div>
            <h3>Event database</h3>
            <p>Supabase Postgres · private Storage · scoped access</p>
          </div>
          <Badge status={snapshot ? "connected" : "unknown"}>
            {snapshot
              ? "Snapshot received"
              : configured
                ? "Configured · unverified"
                : "Not configured"}
          </Badge>
        </div>
        <div className="health-row">
          <div>
            <h3>Finance worker</h3>
            <p>Last heartbeat: {dateTime(snapshot?.worker.last_seen_at)}</p>
          </div>
          <Badge status={snapshot?.worker.status ?? "unknown"} />
        </div>
        {snapshot?.connections.length ? (
          snapshot.connections.map((row, index) => (
            <div className="health-row" key={textValue(row.id, String(index))}>
              <div>
                <h3>
                  {textValue(
                    row.name ?? row.provider ?? row.type,
                    "Provider connection",
                  )}
                </h3>
                <p>
                  {textValue(
                    row.message ?? row.error ?? row.detail,
                    "No connection detail recorded",
                  )}
                </p>
                <RecordDetails value={row} label="Inspect connection health" />
              </div>
              <Badge status={textValue(row.status, "unknown")} />
            </div>
          ))
        ) : (
          <div className="health-row">
            <div>
              <h3>Provider connections</h3>
              <p>
                No verified Gmail, model, or payment connection has been
                received.
              </p>
            </div>
            <Badge status="unknown">Not verified</Badge>
          </div>
        )}
      </div>
      <p className="section-description">
        A configured address or API key alone does not prove a live provider
        call. Connection records and actual worker results determine readiness.
      </p>
    </div>
  );
}
function Obligations({ snapshot }: { snapshot: FinanceSnapshot | null }) {
  if (!snapshot?.obligations.length) return null;
  return (
    <section className="obligations">
      <div className="section-heading">
        <h2>Commitments & receivables</h2>
      </div>
      <div className="table-scroll">
        <table>
          <thead>
            <tr>
              <th>Obligation</th>
              <th>Direction</th>
              <th>Amount</th>
              <th>Settled</th>
              <th>Evidence</th>
            </tr>
          </thead>
          <tbody>
            {snapshot.obligations.map((row) => (
              <tr key={row.id}>
                <td>
                  {row.title}
                  <div>
                    <Badge status={row.status} />
                  </div>
                </td>
                <td>{row.direction}</td>
                <td>{formatMoney(row.amount_minor, row.currency)}</td>
                <td>{formatMoney(row.settled_minor, row.currency)}</td>
                <td>
                  <Badge status={row.evidence_status} />
                  <RecordDetails
                    value={row.source_refs}
                    label="Inspect source references"
                  />
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </section>
  );
}
function SourceRegister({ snapshot }: { snapshot: FinanceSnapshot | null }) {
  return (
    <section className="source-register">
      <div className="section-heading">
        <h2>Source register</h2>
      </div>
      {snapshot?.source_items.length ? (
        snapshot.source_items.map((row, index) => (
          <article
            className="source-row"
            key={textValue(row.id, String(index))}
          >
            <FileText size={17} />
            <div>
              <h3>
                {textValue(
                  asRecord(row.metadata).filename ?? row.external_id ?? row.id,
                  "Source record",
                )}
              </h3>
              <p>
                {textValue(row.source_type)} · Version {textValue(row.version)}
                {asRecord(row.metadata).extraction_status
                  ? ` · ${textValue(asRecord(row.metadata).extraction_status).replaceAll("_", " ")}`
                  : ""}
              </p>
              <RecordDetails
                value={row}
                label="Inspect source version and artifact reference"
              />
              {Boolean(row.artifact_path) && snapshot && (
                <SourceArtifact
                  path={textValue(row.artifact_path)}
                  scope={{
                    organization_id: snapshot.organization.id,
                    run_id: snapshot.run.id,
                  }}
                />
              )}
              {typeof asRecord(row.metadata).raw_artifact_path === "string" &&
                snapshot && (
                  <ArtifactDownload
                    path={textValue(asRecord(row.metadata).raw_artifact_path)}
                    scope={{
                      organization_id: snapshot.organization.id,
                      run_id: snapshot.run.id,
                    }}
                  />
                )}
            </div>
          </article>
        ))
      ) : (
        <p className="muted section-description">
          No persisted source versions are available for this run.
        </p>
      )}
    </section>
  );
}

function SourceArtifact({ path, scope }: { path: string; scope: Scope }) {
  const [busy, setBusy] = useState(false);
  const [failure, setFailure] = useState<string | null>(null);
  async function download() {
    if (!path.startsWith(`${scope.organization_id}/${scope.run_id}/`)) {
      setFailure("The source artifact does not belong to this run.");
      return;
    }
    setBusy(true);
    setFailure(null);
    try {
      const { data, error } = await browserSupabase()
        .storage.from("finance-artifacts")
        .download(path);
      if (error || !data)
        throw new Error("The private source is unavailable to this account.");
      const url = URL.createObjectURL(
        new Blob([data], { type: "application/octet-stream" }),
      );
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = path.split("/").at(-1) ?? "source-document";
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
    } catch (cause) {
      setFailure(
        cause instanceof Error
          ? cause.message
          : "The source could not be read.",
      );
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="source-download">
      <button disabled={busy} onClick={download}>
        <ArrowDownToLine size={13} />
        {busy ? "Downloading…" : "Download private source"}
      </button>
      {failure && <p role="alert">{failure}</p>}
    </div>
  );
}

function OpeningCashForm({
  currency,
  busy,
  onCancel,
  onSubmit,
}: {
  currency: string;
  busy: boolean;
  onCancel: () => void;
  onSubmit: (payload: StateRecord) => Promise<boolean>;
}) {
  const [amount, setAmount] = useState("");
  const [date, setDate] = useState("");
  const [note, setNote] = useState("");
  const [attested, setAttested] = useState(false);
  const [error, setError] = useState<string | null>(null);
  return (
    <form
      className="intake-form opening-form"
      onSubmit={async (event) => {
        event.preventDefault();
        setError(null);
        try {
          await onSubmit(
            openingCashPayload({
              amount,
              currency,
              as_of: date,
              note,
              attested,
            }),
          );
        } catch {
          setError(
            "Check the exact amount, opening date, source note, and attestation before submitting.",
          );
        }
      }}
    >
      <h2>Establish opening cash</h2>
      <p>
        Record the cash your event holds at the start of this run. This is
        owner-attested evidence; bank verification must be recorded separately.
        Once established, opening cash cannot be replaced through this form.
      </p>
      <div className="opening-fields">
        <label>
          Amount ({currency})
          <input
            required
            inputMode="decimal"
            maxLength={40}
            value={amount}
            onChange={(event) => setAmount(event.target.value)}
            placeholder="0.00"
          />
        </label>
        <label>
          Opening balance date (Pacific)
          <input
            required
            type="date"
            value={date}
            onChange={(event) => setDate(event.target.value)}
          />
        </label>
        <label>
          Currency
          <input value={currency} readOnly aria-readonly="true" />
        </label>
      </div>
      <label>
        Source and owner's note
        <textarea
          required
          minLength={3}
          maxLength={2000}
          rows={2}
          value={note}
          onChange={(event) => setNote(event.target.value)}
          placeholder="Identify the account or source used to attest this opening balance."
        />
      </label>
      <label className="review-check">
        <input
          type="checkbox"
          required
          checked={attested}
          onChange={(event) => setAttested(event.target.checked)}
        />
        I am the event director and attest this exact opening balance and
        source.
      </label>
      {error && (
        <p role="alert" className="opening-error">
          {error}
        </p>
      )}
      <div>
        <button type="button" onClick={onCancel} disabled={busy}>
          Cancel
        </button>
        <button className="primary" type="submit" disabled={busy || !attested}>
          Queue attested opening balance <ArrowRight size={14} />
        </button>
      </div>
    </form>
  );
}
