# n8n setup gate

Both workflows are intentionally inactive.

1. Start the local worker with a strong random `YULA_FACTORY_TOKEN`. To accept calls from Docker Desktop, bind the worker on a Docker-reachable host address and keep Windows Firewall restricted to local/private Docker traffic.
2. In n8n, create an **HTTP Header Auth** credential:
   - Header name: `Authorization`
   - Header value: `Bearer <same token>`
   - Run `copy-n8n-token.ps1` to place the full header value on the clipboard without printing or saving it.
3. Select that credential on `Day 1 Package Preflight` and `Write Private Error Log`.
4. Run `Manual Dry-Run Trigger`. The current expected result is `passed: false` because Day 1 is still missing the final `manifest.json` and `qa_report.txt`; this proves the preflight catches incomplete packages.
5. Open the orchestrator’s Workflow Settings and assign `Yula Aria — Content Factory Error Handler (INACTIVE)` as its Error Workflow.
6. Keep both workflows inactive until the Day 1 render is complete, credentialed calls are tested, connections are inspected, and a failure is confirmed in the private SQLite log.

The n8n workflow passes JSON paths only. Video/audio bytes remain on disk and are handled by the Python/FFmpeg worker, avoiding n8n binary-memory overhead.

## Low-token runner

`YULAARIA000003_low_token_job_runner.json` passes only a small job path to the Windows worker. Keep it inactive and manual-only while testing.

1. Import workflow `YULAARIA000003`.
2. Open `_factory` in VS Code, run the test task, then start the local worker task.
3. Run Day 2 locally once. A second run should return `status: cached`.
4. Select the same HTTP Header Auth credential on `Run Local Day Job`.
5. Execute the workflow manually and inspect the returned QA result.
6. Assign the existing error workflow in Workflow Settings before adding any Schedule Trigger.

## Approval-gated social scheduler

`YULAARIA000004_approved_scheduler.json` checks the local ledger every five minutes and dispatches only posts whose exact plan digest was approved. It contains no platform credentials and passes no media bytes.

Keep it inactive until `PUBLISHING_AUTOMATION_SETUP.md` is complete, the HTTP Header Auth credential is selected, the error workflow is assigned, and each provider has passed a controlled one-post test. `YULA_SCHEDULER_LIVE=0` is an independent local kill switch.
