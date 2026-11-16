import assert from "node:assert/strict";
import test from "node:test";

import worker, { dispatchWorkflow } from "../src/index.mjs";

test("dispatches the production workflow in non-seed mode", async () => {
  let request;
  await dispatchWorkflow({ GITHUB_TOKEN: "test-token" }, async (url, options) => {
    request = { url, options };
    return { status: 204 };
  });

  assert.equal(
    request.url,
    "https://api.github.com/repos/AbdullahSoudi/SWE-Jobs/actions/workflows/job_bot.yml/dispatches",
  );
  assert.equal(request.options.method, "POST");
  assert.equal(request.options.headers.Authorization, "Bearer test-token");
  assert.deepEqual(JSON.parse(request.options.body), {
    ref: "main",
    inputs: { seed_mode: "false" },
  });
});

test("fails closed when the token is missing", async () => {
  await assert.rejects(() => dispatchWorkflow({}), /GITHUB_TOKEN is not configured/);
});

test("reports only the status for GitHub failures", async () => {
  await assert.rejects(
    () => dispatchWorkflow({ GITHUB_TOKEN: "secret-value" }, async () => ({ status: 403 })),
    (error) => error.message === "GitHub workflow dispatch failed with status 403" &&
      !error.message.includes("secret-value"),
  );
});

test("scheduled events disable delayed retries", async () => {
  let noRetryCalled = false;
  const originalFetch = globalThis.fetch;
  globalThis.fetch = async () => ({ status: 204 });
  try {
    await worker.scheduled(
      { noRetry() { noRetryCalled = true; } },
      { GITHUB_TOKEN: "test-token" },
    );
  } finally {
    globalThis.fetch = originalFetch;
  }
  assert.equal(noRetryCalled, true);
});

test("public requests cannot dispatch the workflow", async () => {
  const response = await worker.fetch();
  assert.equal(response.status, 404);
});
