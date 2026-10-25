import assert from "node:assert/strict";
import test from "node:test";
import { authErrorMessage, financeReturnPath } from "../src/lib/auth";
import { publicConfig } from "../src/lib/config";

test("sign-in preserves only a complete event scope, never arbitrary redirects", () => {
  const org = "11111111-1111-1111-1111-111111111111";
  const run = "22222222-2222-2222-2222-222222222222";
  assert.equal(
    financeReturnPath(
      `?organization_id=${org}&run_id=${run}&next=https://outside.invalid`,
    ),
    `/desk?organization_id=${org}&run_id=${run}`,
  );
  assert.equal(
    financeReturnPath(
      `?organization_id=${org}&run_id=invalid&next=//outside.invalid`,
    ),
    "/desk",
  );
});

test("auth errors explain credentials, confirmation, email limits, and disabled signup safely", () => {
  assert.match(authErrorMessage({ code: "invalid_credentials" }), /Check both/);
  assert.match(
    authErrorMessage({ code: "email_not_confirmed" }),
    /Confirm your email/,
  );
  assert.match(
    authErrorMessage({ code: "email_not_confirmed" }),
    /browser where you created/,
  );
  assert.match(
    authErrorMessage({ code: "over_email_send_rate_limit" }),
    /Wait a few minutes/,
  );
  assert.match(
    authErrorMessage({ code: "email_address_not_authorized" }),
    /current email setup/,
  );
  assert.match(
    authErrorMessage({ code: "signup_disabled" }),
    /create your account/,
  );
  assert.match(
    authErrorMessage({ code: "email_provider_disabled" }),
    /enable it/,
  );
  assert.match(
    authErrorMessage({ code: "weak_password" }),
    /stronger password/,
  );
});

test("unknown auth failures never reflect provider detail or credentials", () => {
  const providerError = {
    code: "unrecognized",
    status: 500,
    message: "provider-secret-fixture",
  };
  const message = authErrorMessage(providerError);
  assert.equal(message.includes(providerError.message), false);
  assert.match(message, /Check your connection/);
  assert.match(authErrorMessage({ status: 429 }), /Wait a few minutes/);
  assert.match(authErrorMessage(null), /event owner/);
});

test("missing or invalid Supabase public configuration cannot enable authentication", () => {
  const previousUrl = process.env.NEXT_PUBLIC_SUPABASE_URL;
  const previousKey = process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
  try {
    delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    delete process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
    assert.equal(publicConfig(), null);
    process.env.NEXT_PUBLIC_SUPABASE_URL = "https://fixture.invalid";
    assert.equal(publicConfig(), null);
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = "sb_publishable_fixture";
    process.env.NEXT_PUBLIC_SUPABASE_URL = "javascript:fixture";
    assert.equal(publicConfig(), null);
  } finally {
    if (previousUrl === undefined) delete process.env.NEXT_PUBLIC_SUPABASE_URL;
    else process.env.NEXT_PUBLIC_SUPABASE_URL = previousUrl;
    if (previousKey === undefined)
      delete process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY;
    else process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY = previousKey;
  }
});
