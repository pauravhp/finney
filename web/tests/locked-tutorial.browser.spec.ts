import { expect, test, type Page } from "@playwright/test";
import { buildSync } from "esbuild";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import {
  tutorialCaseId,
  tutorialFinding,
  tutorialSnapshot,
} from "./locked-tutorial-fixture";

// Real React/DOM/input behavior, with only the scoped queue/snapshot transport
// scripted. No provider, database or hosted session is contacted.
const origin = "http://locked-tutorial.test.invalid";
const bundle = buildSync({
  stdin: {
    contents: `
import React from 'react'; import {createRoot} from 'react-dom/client';
import {LockedTutorial} from './src/components/locked-tutorial';
const root=createRoot(document.getElementById('root'));
window.actions=[]; window.requests=0; window.shortcutCount=0;
document.addEventListener('keydown',event=>{if(event.key==='k')window.shortcutCount++;});
function render(){root.render(<App {...window.fixture}/>);}
window.updateTutorialFixture=(patch)=>{window.fixture={...window.fixture,...patch};render();};
window.completeReview=(jobId,status,withResult=true)=>{
 const snapshot=structuredClone(window.fixture.snapshot);
 snapshot.jobs=snapshot.jobs.map(job=>job.id===jobId?{...job,status}:job);
 if(withResult)snapshot.cases[0].data.finding={kind:'prepared_agent_review',verification:'unverified_model_recommendation',effects_completed:false,decision:'needs_review',explanation:'The changed invoice needs your decision. No payment was made.',provenance:{job_id:jobId,actor_trace_id:'fixture-trace'}};
 window.updateTutorialFixture({snapshot});
};
function App(props){
 const selected=props.selectedCaseId;
 const working=props.snapshot.jobs.some(job=>job.status==='queued'||job.status==='running');
 const latest=props.snapshot.jobs.at(-1);const finishing=latest?.status==='completed'&&props.snapshot.cases[0].data.finding?.provenance?.job_id!==latest.id;
 const navigate=(tab,caseId)=>{window.actions.push('navigate:'+tab);window.updateTutorialFixture({tab,selectedCaseId:caseId??selected});};
 const review=()=>{
  const jobId='review-'+(++window.requests);window.actions.push(jobId);
  const snapshot=structuredClone(props.snapshot);snapshot.jobs.push({id:jobId,command_type:'review_case',case_id:selected,status:'queued'});
  window.updateTutorialFixture({snapshot,lastCommand:{jobId,type:'review_case',caseId:selected}});
 };
 return <><main><header><button id='outside' onClick={()=>window.actions.push('outside')} onPointerDown={()=>window.actions.push('outside-pointer')} onTouchStart={()=>window.actions.push('outside-touch')}>Unrelated action</button><input aria-label='Unrelated input'/></header>
 <section id='existing-inert' inert><button>Already inert</button></section>
 <aside><h1>Hack Harbor</h1><p>Five days to go</p><button data-tutorial='open-alert' onClick={()=>{window.actions.push('alert');navigate('cases',props.snapshot.cases[0].id);}}>Open Finney’s alert</button><div data-tutorial={working||finishing?'finney-working':undefined} className='fixture-working'><img src='/brand/finney.svg' alt=''/><p>{finishing?'Finishing up.':working?'Finney is working…':'Ready to review'}</p><button id='working-unrelated' onClick={()=>window.actions.push('working-unrelated')}>Unrelated status action</button></div></aside>
 {selected&&props.tab==='cases'&&<section className='fixture-case'><h2>Changed AV invoice</h2><p>The revised invoice and previous commitment are on file.</p><button data-tutorial='review-case' onClick={review} disabled={working}>Review case</button>{props.snapshot.cases[0].data.finding&&<button data-tutorial='view-budget' onClick={()=>navigate('overview')}>See budget</button>}</section>}
 {props.tab==='overview'&&<section><h2>Event budget</h2><p>Recorded cash: {props.snapshot.position.cash_minor}</p></section>}
 </main>{props.show&&<LockedTutorial {...props} onNavigate={navigate}/>}</>;
}
render();`,
    resolveDir: process.cwd(),
    loader: "tsx",
  },
  bundle: true,
  write: false,
  format: "iife",
  platform: "browser",
  jsx: "automatic",
  tsconfig: resolve("tsconfig.json"),
  define: { "process.env.NODE_ENV": '"production"' },
}).outputFiles[0].text;

async function mount(page: Page, patch: Record<string, unknown> = {}) {
  let props = {
    snapshot: structuredClone(tutorialSnapshot),
    selectedCaseId: null,
    tab: "cases",
    lastCommand: null,
    show: false,
    ...patch,
  };
  const errors: string[] = [];
  page.on("pageerror", (error) => errors.push(error.message));
  await page.route(`${origin}/**`, async (route) => {
    const path = new URL(route.request().url()).pathname;
    if (path === "/brand/locked-tutorial.css")
      return route.fulfill({
        contentType: "text/css",
        body: readFileSync(resolve("public/brand/locked-tutorial.css"), "utf8"),
      });
    if (path === "/brand/finney.svg")
      return route.fulfill({
        contentType: "image/svg+xml",
        body: readFileSync(resolve("public/brand/finney.svg"), "utf8"),
      });
    return route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"/><style>${readFileSync(resolve("src/app/globals.css"), "utf8")} main{max-width:1000px;margin:0 auto;padding:24px} header{display:flex;gap:16px;margin-bottom:40px} aside{padding:24px;background:#eaf0e2;width:min(390px,100%)} .fixture-working{margin-top:24px} .fixture-working img{width:64px;height:64px} .fixture-case{margin:40px 0} .fixture-case button{margin-right:16px} @media(max-width:600px){header{flex-direction:column}}</style></head><body><div id="root"></div><script>window.fixture=${JSON.stringify(props).replaceAll("<", "\\u003c")};${bundle.replaceAll("</script", "<\\/script")}</script></body></html>`,
    });
  });
  await page.goto(origin);
  await page.locator("#outside").focus();
  await page.evaluate(() =>
    (window as any).updateTutorialFixture({ show: true }),
  );
  await expect(
    page.getByRole("button", { name: "Let’s go", exact: true }),
  ).toBeVisible();
  return {
    errors,
    setReloadProps: (next: Record<string, unknown>) => {
      props = { ...props, ...next };
    },
  };
}

async function startReview(page: Page) {
  await page.getByRole("button", { name: "Let’s go", exact: true }).click();
  await page.locator("[data-tutorial='open-alert']").click();
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "review",
  );
  await page.locator("[data-tutorial='review-case']").click();
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "waiting",
  );
}

test("locks mouse, touch and keyboard to the expected action; Skip restores focus and existing inert state", async ({
  page,
}) => {
  const { errors } = await mount(page);
  await page.evaluate(() => {
    document.getElementById("outside")!.click();
    document.getElementById("outside")!.dispatchEvent(
      new PointerEvent("pointerdown", {
        bubbles: true,
        cancelable: true,
        pointerType: "touch",
      }),
    );
    document
      .getElementById("outside")!
      .dispatchEvent(
        new Event("touchstart", { bubbles: true, cancelable: true }),
      );
    document.querySelector<HTMLInputElement>("input")!.focus();
  });
  await page.keyboard.press("k");
  await page.keyboard.press("Control+k");
  expect(await page.evaluate(() => (window as any).actions)).toEqual([]);
  expect(await page.evaluate(() => (window as any).shortcutCount)).toBe(0);
  expect(
    await page.evaluate(() => {
      const event = new KeyboardEvent("keydown", {
        key: "r",
        ctrlKey: true,
        cancelable: true,
        bubbles: true,
      });
      window.dispatchEvent(event);
      return event.defaultPrevented;
    }),
  ).toBe(false);
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Skip demo", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Shift+Tab");
  await expect(
    page.getByRole("button", { name: "Let’s go", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Enter");
  await expect(page.locator("[data-tutorial='open-alert']")).toBeFocused();
  await page.evaluate(() => {
    document.querySelector<HTMLElement>("main")!.style.minHeight = "1800px";
    window.scrollTo({ top: 80, behavior: "instant" });
  });
  await expect
    .poll(async () =>
      page.evaluate(() => {
        const target = document
          .querySelector("[data-tutorial='open-alert']")!
          .getBoundingClientRect();
        const outline = document
          .querySelector(".locked-tutorial-outline")!
          .getBoundingClientRect();
        return Math.abs(outline.top - Math.max(0, target.top - 6));
      }),
    )
    .toBeLessThan(1);
  await page.keyboard.press("Tab");
  await expect(
    page.getByRole("button", { name: "Skip demo", exact: true }),
  ).toBeFocused();
  await page.keyboard.press("Escape");
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  await expect(page.locator("#outside")).toBeFocused();
  expect(
    await page.locator("#existing-inert").getAttribute("inert"),
  ).not.toBeNull();
  expect(await page.locator("main").getAttribute("inert")).toBeNull();
  await page.locator("#outside").click();
  expect(await page.evaluate(() => (window as any).actions)).toEqual([
    "outside-pointer",
    "outside",
  ]);
  expect(errors).toEqual([]);
});

test("waits for this accepted job and its persisted review, then uses the real budget action", async ({
  page,
}, info) => {
  const stale = structuredClone(tutorialSnapshot);
  stale.jobs = [
    {
      id: "old-job",
      command_type: "review_case",
      case_id: tutorialCaseId,
      status: "completed",
    },
  ];
  stale.cases[0].data.finding = tutorialFinding("old-job");
  const { errors } = await mount(page, {
    snapshot: stale,
    lastCommand: {
      jobId: "old-job",
      type: "review_case",
      caseId: tutorialCaseId,
    },
  });
  await startReview(page);
  await expect(
    page.locator("[data-tutorial='finney-working'] img"),
  ).toBeVisible();
  await expect(page.locator(".locked-tutorial-coach")).toHaveCount(0);
  await expect(
    page.getByText("Finney is working…", { exact: true }),
  ).toBeVisible();
  // If the real status is briefly unavailable, keep a readable fallback.
  await page.evaluate(() =>
    document
      .querySelector("[data-tutorial='finney-working']")!
      .removeAttribute("data-tutorial"),
  );
  await expect(
    page.getByText("Finney’s on it.", { exact: true }),
  ).toBeVisible();
  await page.evaluate(() =>
    document
      .querySelector(".fixture-working")!
      .setAttribute("data-tutorial", "finney-working"),
  );
  await expect(page.locator(".locked-tutorial-coach")).toHaveCount(0);
  await expect(page.locator(".locked-tutorial-outline")).toBeVisible();
  await page.evaluate(() =>
    document.getElementById("working-unrelated")!.click(),
  );
  expect(await page.evaluate(() => (window as any).actions)).not.toContain(
    "working-unrelated",
  );
  await page.evaluate(() =>
    (window as any).completeReview("old-job", "completed"),
  );
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "waiting",
  );
  await page.evaluate(() =>
    (window as any).completeReview("review-1", "completed", false),
  );
  await expect(page.getByText("Finishing up.", { exact: true })).toBeVisible();
  await expect(page.locator(".locked-tutorial-coach")).toHaveCount(0);
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "waiting",
  );
  await page.evaluate(() =>
    (window as any).completeReview("review-1", "completed", true),
  );
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "budget",
  );
  await page.screenshot({
    path: `test-results/${info.project.name}-locked-tutorial-budget.png`,
    fullPage: true,
  });
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= innerWidth,
    ),
  ).toBe(true);
  await page.locator("[data-tutorial='view-budget']").click();
  await expect(page.getByText("You’re ready.", { exact: true })).toBeVisible();
  await expect(
    page.locator("h2").filter({ hasText: "Event budget" }),
  ).toBeVisible();
  await page.getByRole("button", { name: "Done", exact: true }).click();
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  expect(
    await page.evaluate(
      () => (window as any).fixture.snapshot.position.cash_minor,
    ),
  ).toBe("180000");
  expect(errors).toEqual([]);
});

test("reload resumes the exact pending job; failure permits explicit real retry without auto success", async ({
  page,
}) => {
  const mounted = await mount(page);
  await startReview(page);
  const snapshot = await page.evaluate(() => (window as any).fixture.snapshot);
  mounted.setReloadProps({
    show: true,
    snapshot,
    selectedCaseId: null,
    lastCommand: null,
  });
  await page.reload();
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "waiting",
  );
  await expect(page.locator(".fixture-case")).toBeVisible();
  expect(await page.evaluate(() => (window as any).requests)).toBe(0);
  await page.evaluate(() =>
    (window as any).completeReview("review-1", "failed", false),
  );
  await expect(
    page.getByText(
      "The review didn’t finish. Review again, or skip the demo.",
      { exact: true },
    ),
  ).toBeVisible();
  await expect(page.locator("[data-tutorial='review-case']")).toBeEnabled();
  // A fresh transport ID after reload, rather than accidentally reusing review-1.
  await page.evaluate(() => {
    (window as any).requests = 1;
  });
  await page.locator("[data-tutorial='review-case']").click();
  await expect(
    page.locator("[data-tutorial='finney-working'] img"),
  ).toBeVisible();
  await expect(page.locator(".locked-tutorial-coach")).toHaveCount(0);
  await page.evaluate(() =>
    (window as any).completeReview("review-1", "completed", true),
  );
  await expect(page.locator(".locked-tutorial")).toHaveAttribute(
    "data-tutorial-phase",
    "waiting",
  );
  await page.getByRole("button", { name: "Skip demo", exact: true }).click();
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  await page.reload();
  await expect(page.locator("#outside")).toBeVisible();
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  expect(mounted.errors).toEqual([]);
});

test("unmount releases the lock, and a different run starts fresh", async ({
  page,
}) => {
  await mount(page);
  await page.evaluate(() =>
    (window as any).updateTutorialFixture({ show: false }),
  );
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  await expect(page.locator("#outside")).toBeFocused();
  await page.locator("#outside").click();
  await page.evaluate(() =>
    (window as any).updateTutorialFixture({ show: true }),
  );
  await page.getByRole("button", { name: "Skip demo", exact: true }).click();
  await page.evaluate(() => {
    const snapshot = structuredClone((window as any).fixture.snapshot);
    snapshot.run.id = "d19587c6-6535-4455-b4cd-ea4819845ec9";
    (window as any).updateTutorialFixture({ snapshot });
  });
  await expect(
    page.getByRole("button", { name: "Let’s go", exact: true }),
  ).toBeVisible();
  await page.keyboard.press("Escape");
  await page.evaluate(() => {
    const snapshot = structuredClone((window as any).fixture.snapshot);
    snapshot.run.id = "d19587c6-6535-4455-b4cd-ea4819845ed0";
    snapshot.run.status = "archived";
    (window as any).updateTutorialFixture({ snapshot });
  });
  await expect(page.locator(".locked-tutorial")).toHaveCount(0);
  await page.locator("#outside").click();
});
