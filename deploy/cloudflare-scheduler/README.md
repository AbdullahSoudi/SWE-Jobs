# Free external scheduler

This Cloudflare Worker dispatches the existing `job_bot.yml` workflow at
`:07`, `:22`, `:37`, and `:52` UTC. It moves only the scheduling signal outside
GitHub; the bot and its SQLite snapshot remain in GitHub Actions.

The Worker is compatible with the Cloudflare Workers Free plan. It uses one
Cron Trigger invocation every 15 minutes and one GitHub API request per
invocation. The repository is public, so its standard GitHub-hosted Linux
runner usage is free. Do not select a paid Workers plan or a GitHub larger
runner.

## Security model

- The Worker has no public dispatch endpoint. HTTP requests receive `404`.
- `GITHUB_TOKEN` is a Cloudflare secret and must never be committed.
- Use a fine-grained GitHub personal access token restricted to the
  `AbdullahSoudi/SWE-Jobs` repository with only **Actions: Read and write**.
- The scheduler always dispatches `main` with `seed_mode=false`.
- Cloudflare retries are disabled to avoid delayed duplicate dispatches.

## Deploy

1. Create or sign in to a Cloudflare account on the Free plan.
2. Create the restricted GitHub token described above.
3. From this directory, authenticate Wrangler and add the secret:

   ```sh
   npx wrangler login
   npx wrangler secret put GITHUB_TOKEN
   ```

4. Deploy the Worker and its Cron Trigger:

   ```sh
   npx wrangler deploy
   ```

5. Wait up to 15 minutes for Cron Trigger propagation. Verify at least three
   successive Cloudflare cron events and matching GitHub `workflow_dispatch`
   runs before removing the native GitHub `schedule` entry.

Keep the native GitHub schedule during initial verification. Both triggers may
briefly coexist; the workflow concurrency group prevents overlap, and the
persisted database prevents already-sent jobs from being sent again.

Run the local unit tests with:

```sh
node --test test/scheduler.test.mjs
```
