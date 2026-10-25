import assert from "node:assert/strict";
import test from "node:test";
import {
  createGuestDemo,
  guestDemoEntryEnabled,
  guestDemoErrorMessage,
  GuestDemoError,
  guestDemoReturnPath,
} from "../src/lib/guest-demo";

const organization_id = "d19587c6-6535-4455-b4cd-ea4819845ec1";
const run_id = "d19587c6-6535-4455-b4cd-ea4819845ec2";
const anonymousSession = {
  access_token: "guest-access-token-fixture",
  user: { is_anonymous: true },
};

function response(status: number, body: unknown = { organization_id, run_id }) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
  };
}

test("guest entry is opt-in only when the public flag is exactly true", () => {
  assert.equal(guestDemoEntryEnabled(undefined), false);
  assert.equal(guestDemoEntryEnabled("false"), false);
  assert.equal(guestDemoEntryEnabled("TRUE"), false);
  assert.equal(guestDemoEntryEnabled("true"), true);
});

test("disabled entry does not inspect Auth or contact the finance route", async () => {
  let authCalls = 0;
  let fetchCalls = 0;
  await assert.rejects(
    createGuestDemo({
      enabled: false,
      auth: {
        async getSession() {
          authCalls += 1;
          return { data: { session: null }, error: null };
        },
        async signInAnonymously() {
          authCalls += 1;
          return { data: { session: null, user: null }, error: null };
        },
      },
      async fetcher() {
        fetchCalls += 1;
        return response(201);
      },
    }),
    (error: unknown) => {
      assert.ok(error instanceof GuestDemoError);
      assert.equal(error.code, "disabled");
      return true;
    },
  );
  assert.equal(authCalls, 0);
  assert.equal(fetchCalls, 0);
});

test("anonymous SDK sign-in then same-origin POST opens only the validated run", async () => {
  const sequence: string[] = [];
  let request: RequestInit | undefined;
  const destination = await createGuestDemo({
    enabled: true,
    auth: {
      async getSession() {
        sequence.push("get-session");
        return { data: { session: null }, error: null };
      },
      async signInAnonymously() {
        sequence.push("anonymous-sign-in");
        return {
          data: { session: anonymousSession, user: anonymousSession.user },
          error: null,
        };
      },
    },
    async fetcher(input, init) {
      sequence.push("create-demo");
      assert.equal(input, "/api/finance/demo");
      request = init;
      return response(201, {
        organization_id,
        run_id,
        next: "https://outside.invalid",
      });
    },
  });

  assert.deepEqual(sequence, [
    "get-session",
    "anonymous-sign-in",
    "create-demo",
  ]);
  assert.equal(request?.method, "POST");
  assert.equal(request?.credentials, "same-origin");
  assert.equal(request?.cache, "no-store");
  assert.equal(
    new Headers(request?.headers).get("content-type"),
    "application/json",
  );
  assert.equal(new Headers(request?.headers).has("authorization"), false);
  assert.deepEqual(JSON.parse(String(request?.body)), {
    name: "Guest finance demo",
  });
  assert.equal(
    destination,
    `/desk?organization_id=${organization_id}&run_id=${run_id}`,
  );
});

test("an existing regular account session is never reused for a guest request", async () => {
  let signInCalls = 0;
  let fetchCalls = 0;
  await assert.rejects(
    createGuestDemo({
      enabled: true,
      auth: {
        async getSession() {
          return {
            data: {
              session: {
                access_token: "owner-token-fixture",
                user: { is_anonymous: false },
              },
            },
            error: null,
          };
        },
        async signInAnonymously() {
          signInCalls += 1;
          return {
            data: { session: anonymousSession, user: anonymousSession.user },
            error: null,
          };
        },
      },
      async fetcher() {
        fetchCalls += 1;
        return response(201);
      },
    }),
    (error: unknown) => {
      assert.ok(error instanceof GuestDemoError);
      assert.equal(error.code, "account_session_active");
      return true;
    },
  );
  assert.equal(signInCalls, 0);
  assert.equal(fetchCalls, 0);
  assert.match(
    guestDemoErrorMessage(new GuestDemoError("account_session_active")),
    /Sign out/,
  );
});

test("provider-disabled and CAPTCHA failures are actionable and never create a run", async (t) => {
  for (const [code, expected, copy] of [
    [
      "anonymous_provider_disabled",
      "anonymous_provider_disabled",
      /enable anonymous sign-ins/,
    ],
    ["signup_disabled", "signup_disabled", /new guest identities/],
    ["captcha_failed", "captcha_required", /CAPTCHA/],
  ] as const) {
    await t.test(code, async () => {
      let fetchCalls = 0;
      await assert.rejects(
        createGuestDemo({
          enabled: true,
          auth: {
            async getSession() {
              return { data: { session: null }, error: null };
            },
            async signInAnonymously() {
              return {
                data: { session: null, user: null },
                error: { code },
              };
            },
          },
          async fetcher() {
            fetchCalls += 1;
            return response(201);
          },
        }),
        (error: unknown) => {
          assert.ok(error instanceof GuestDemoError);
          assert.equal(error.code, expected);
          assert.match(guestDemoErrorMessage(error), copy);
          return true;
        },
      );
      assert.equal(fetchCalls, 0);
    });
  }
});

test("a returned non-anonymous identity fails closed before API access", async () => {
  let fetchCalls = 0;
  await assert.rejects(
    createGuestDemo({
      enabled: true,
      auth: {
        async getSession() {
          return { data: { session: null }, error: null };
        },
        async signInAnonymously() {
          return {
            data: {
              session: {
                access_token: "unexpected-owner-token-fixture",
                user: { is_anonymous: false },
              },
              user: { is_anonymous: false },
            },
            error: null,
          };
        },
      },
      async fetcher() {
        fetchCalls += 1;
        return response(201);
      },
    }),
    (error: unknown) => {
      assert.ok(error instanceof GuestDemoError);
      assert.equal(error.code, "not_anonymous");
      return true;
    },
  );
  assert.equal(fetchCalls, 0);
});

test("network and authenticated API failures stay visible and do not redirect", async (t) => {
  await t.test("Auth network error", async () => {
    await assert.rejects(
      createGuestDemo({
        enabled: true,
        auth: {
          async getSession() {
            return { data: { session: null }, error: null };
          },
          async signInAnonymously() {
            throw new TypeError("network fixture");
          },
        },
        async fetcher() {
          assert.fail("finance route must not be called");
        },
      }),
      (error: unknown) => {
        assert.match(guestDemoErrorMessage(error), /Check your connection/);
        return true;
      },
    );
  });

  await t.test("session rejected by authenticated route", async () => {
    await assert.rejects(
      createGuestDemo({
        enabled: true,
        auth: {
          async getSession() {
            return { data: { session: null }, error: null };
          },
          async signInAnonymously() {
            return {
              data: { session: anonymousSession, user: anonymousSession.user },
              error: null,
            };
          },
        },
        async fetcher() {
          return response(401);
        },
      }),
      (error: unknown) => {
        assert.ok(error instanceof GuestDemoError);
        assert.equal(error.code, "session_rejected");
        assert.match(
          guestDemoErrorMessage(error),
          /could not verify that session/,
        );
        return true;
      },
    );
  });

  await t.test(
    "finance route network failure is reported as uncertain",
    async () => {
      await assert.rejects(
        createGuestDemo({
          enabled: true,
          auth: {
            async getSession() {
              return { data: { session: null }, error: null };
            },
            async signInAnonymously() {
              return {
                data: {
                  session: anonymousSession,
                  user: anonymousSession.user,
                },
                error: null,
              };
            },
          },
          async fetcher() {
            throw new TypeError("lost-response fixture");
          },
        }),
        (error: unknown) => {
          assert.match(
            guestDemoErrorMessage(error),
            /creation status is unknown/,
          );
          return true;
        },
      );
    },
  );
});

test("returned scope must be a complete UUID pair before redirect construction", () => {
  assert.throws(
    () =>
      guestDemoReturnPath({
        organization_id,
        run_id: "//outside.invalid",
        next: "https://outside.invalid",
      }),
    (error: unknown) =>
      error instanceof GuestDemoError && error.code === "invalid_scope",
  );
  assert.equal(
    guestDemoReturnPath({ organization_id, run_id }),
    `/desk?organization_id=${organization_id}&run_id=${run_id}`,
  );
});
