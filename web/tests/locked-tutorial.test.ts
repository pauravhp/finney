import assert from "node:assert/strict";
import test from "node:test";
import {
  tutorialHasPersistedResult,
  tutorialStorageKey,
  LOCKED_TUTORIAL_VERSION,
} from "../src/components/locked-tutorial";
import {
  tutorialCaseId,
  tutorialFinding,
  tutorialSnapshot,
} from "./locked-tutorial-fixture";

const command = {
  jobId: "new-job",
  type: "review_case",
  caseId: tutorialCaseId,
};
const completed = () => ({
  ...structuredClone(tutorialSnapshot),
  jobs: [
    {
      id: command.jobId,
      case_id: tutorialCaseId,
      command_type: command.type,
      status: "completed",
    },
  ],
  cases: [
    {
      ...tutorialSnapshot.cases[0],
      data: { finding: tutorialFinding(command.jobId) },
    },
  ],
});

test("tutorial success requires the exact job and guarded persisted review", () => {
  assert.equal(tutorialHasPersistedResult(completed(), command), true);
  for (const status of [
    "queued",
    "running",
    "failed",
    "blocked",
    "cancelled",
  ]) {
    const snapshot = completed();
    snapshot.jobs[0].status = status;
    assert.equal(tutorialHasPersistedResult(snapshot, command), false);
  }
  for (const patch of [
    { id: "prior-job" },
    { case_id: "another-case" },
    { command_type: "director_message" },
  ]) {
    const snapshot = completed();
    Object.assign(snapshot.jobs[0], patch);
    assert.equal(tutorialHasPersistedResult(snapshot, command), false);
  }
  const stale = completed();
  stale.cases[0].data.finding = tutorialFinding("prior-job");
  assert.equal(tutorialHasPersistedResult(stale, command), false);
  const missing = completed();
  missing.cases[0].data = {} as (typeof missing.cases)[0]["data"];
  assert.equal(tutorialHasPersistedResult(missing, command), false);
});

test("unpersisted output and malformed review markers do not graduate the demo", () => {
  for (const patch of [
    { kind: "model_output" },
    { verification: "unknown" },
    { explanation: " " },
    { decision: "A prose decision" },
    { provenance: { job_id: command.jobId } },
  ]) {
    const snapshot = completed();
    Object.assign(snapshot.cases[0].data.finding, patch);
    assert.equal(tutorialHasPersistedResult(snapshot, command), false);
  }
});

test("saved progress is isolated by organization, run, and tutorial version", () => {
  const key = tutorialStorageKey(tutorialSnapshot);
  assert.ok(key.includes(LOCKED_TUTORIAL_VERSION));
  for (const snapshot of [
    {
      ...tutorialSnapshot,
      organization: { ...tutorialSnapshot.organization, id: "another-org" },
    },
    {
      ...tutorialSnapshot,
      run: { ...tutorialSnapshot.run, id: "another-run" },
    },
  ])
    assert.notEqual(tutorialStorageKey(snapshot), key);
});
