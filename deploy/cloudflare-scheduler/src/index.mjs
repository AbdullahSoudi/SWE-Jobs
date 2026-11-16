const REPOSITORY = "AbdullahSoudi/SWE-Jobs";
const WORKFLOW = "job_bot.yml";
const REF = "main";

export async function dispatchWorkflow(env, fetchImpl = fetch) {
  if (!env?.GITHUB_TOKEN) {
    throw new Error("GITHUB_TOKEN is not configured");
  }

  const response = await fetchImpl(
    `https://api.github.com/repos/${REPOSITORY}/actions/workflows/${WORKFLOW}/dispatches`,
    {
      method: "POST",
      headers: {
        Accept: "application/vnd.github+json",
        Authorization: `Bearer ${env.GITHUB_TOKEN}`,
        "Content-Type": "application/json",
        "User-Agent": "swe-jobs-cloudflare-scheduler",
        "X-GitHub-Api-Version": "2022-11-28",
      },
      body: JSON.stringify({
        ref: REF,
        inputs: { seed_mode: "false" },
      }),
    },
  );

  if (response.status !== 204) {
    // Do not include the response body: authentication failures can echo
    // request context that should stay out of Cloudflare logs.
    throw new Error(`GitHub workflow dispatch failed with status ${response.status}`);
  }
}

export default {
  async scheduled(controller, env) {
    // A delayed retry could create a duplicate Actions run. The next 15-minute
    // tick is safer because the bot persists its delivery state between runs.
    controller.noRetry();
    await dispatchWorkflow(env);
  },

  async fetch() {
    // This Worker is cron-only. A public request must never trigger the bot.
    return new Response("Not found", { status: 404 });
  },
};
