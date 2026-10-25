import { spawnSync } from "node:child_process";

// Public, unusable fixture configuration only. Browser requests are intercepted
// by auth.browser.spec.ts. No hosted Auth provider is contacted.
const env = {
  ...process.env,
  NEXT_PUBLIC_SUPABASE_URL: "https://finance-auth.test.invalid",
  NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY: "sb_publishable_browser_fixture",
  FINANCE_AUTH_BROWSER_FIXTURE: "1",
};
let status = 0;
try {
  for (const args of [
    ["run", "build"],
    ["exec", "playwright", "test", "auth.browser.spec.ts"],
  ]) {
    const result = spawnSync("npm", args, { env, stdio: "inherit" });
    if (result.error) throw result.error;
    if (result.status !== 0) {
      status = result.status ?? 1;
      break;
    }
  }
} finally {
  // Leave the workspace with its normal build, even after a fixture-test failure.
  const restored = spawnSync("npm", ["run", "build"], {
    env: process.env,
    stdio: "inherit",
  });
  if (restored.error) throw restored.error;
  if (restored.status !== 0) status = restored.status ?? 1;
}
process.exitCode = status;
