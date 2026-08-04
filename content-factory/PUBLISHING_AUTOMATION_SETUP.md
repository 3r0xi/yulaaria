# Yula Aria Publishing Automation 0.4.1

## Provider map

- Meta Graph API: Facebook Page, Instagram professional account, and Threads.
- YouTube Data API: YouTube Shorts upload and scheduled publication.
- Buffer API: X, with Threads available only as an optional fallback.
- TikTok Content Posting API: local Direct Post at the SQLite due time. Local video files use `FILE_UPLOAD`; photo posts use verified HTTPS URLs.

The local SQLite ledger is the source of truth. Codex controls the Windows worker and desktop scripts directly; n8n is optional and is not required for scheduling. Duplicate submissions are blocked by a unique idempotency key.

## Safety gates

1. Validate and store the plan. This does not use the network.
2. Review the returned plan ID and SHA-256 digest.
3. Approve that exact digest. This still does not use the network.
4. Keep `YULA_SCHEDULER_LIVE=0` through credential and one-post tests.
5. Set it to `1` only after every selected provider passes a private/unlisted or controlled test.

## Local commands

```powershell
.\run.ps1 schedule-validate-plan --plan examples\cross_platform_schedule_plan.example.json --skip-files
.\run.ps1 schedule-store-plan --plan examples\cross_platform_schedule_plan.example.json --skip-files
.\run.ps1 schedule-approve --plan-id 1 --digest <exact-digest>
.\run.ps1 schedule-dispatch
.\run.ps1 schedule-submit-now --plan-id 1 --platform youtube
.\run.ps1 schedule-submit-now --plan-id 1 --platform youtube --live
.\run.ps1 schedule-status --plan-id 1
```

`schedule-dispatch` is a dry run. Live requests require both `--live` and `YULA_SCHEDULER_LIVE=1`.

`schedule-submit-now` immediately hands an approved future post to providers that offer native scheduling. It currently supports YouTube and Buffer. Facebook and Instagram calendar entries are created in Meta Business Suite because the current Graph API publisher would publish them immediately; after a successful UI schedule, use `schedule-record-external` to update the local ledger.

TikTok does not expose a native future scheduling field. Approved TikTok posts use `provider: "tiktok"` and remain in SQLite until `schedule-dispatch --live` runs at the due time. This removes the manual TikTok upload step, but the computer and Windows scheduled task must be running at that time. The default is `privacy_level: "SELF_ONLY"`; public visibility must not be enabled until TikTok has audited the client.

## Credentials

Run `configure-publishing.ps1` after creating Meta credentials. Public IDs and DPAPI-encrypted secrets are stored in the git-ignored `secrets/providers.local.json` vault. Live publishing remains disabled.

TikTok client credentials are stored through `configure-tiktok.ps1`. After the app is approved and Login Kit authorization grants `video.publish`, store the returned user access and refresh tokens with `configure-tiktok.ps1 -IncludeUserTokens`. Client credentials alone cannot publish to a creator account. The publisher refreshes expiring user tokens and saves rotated tokens back into the encrypted vault. No TikTok API call is made during configuration.

For app review, record the real website/app and show the complete flow: sign in with TikTok, select an approved local export, display current creator/privacy choices, obtain explicit consent, submit the video, and show the final status. The domain visible in the recording must match the submitted website URL. Use Sandbox before approval; include every requested product and scope. TikTok accepts up to five demo videos, each no larger than 50 MB.

For YouTube, install the optional publishing dependencies, open a fresh terminal, then run:

```powershell
.\install-publishing-dependencies.ps1
.\run.ps1 youtube-authorize
```

The first run prints a local OAuth consent URL. After consent, the refresh token is DPAPI-encrypted in the local JSON vault.

## Media delivery requirement

Instagram and Threads must be able to fetch media over HTTPS. The default zero-cost path is the local signed-media endpoint plus a Cloudflare Quick Tunnel. Run `start-free-media-tunnel.ps1` before a due Meta dispatch. The scheduler generates a short-lived HMAC-signed URL at dispatch time; Google Drive remains the archive/source of truth and is never made public.

Quick Tunnel URLs change after restart and have no uptime guarantee, so the computer, local worker, and tunnel must remain running until Meta finishes ingesting the asset. R2 remains an optional later upgrade for stable object URLs, not a requirement for the current free setup.

Editable platform times and the organic-content disclosure default live in `config/publishing.defaults.json`.

## Desktop scheduling

`start-desktop-worker.ps1` starts the token-protected local API. `run-desktop-scheduler.ps1` dispatches due posts and appends a local log. Register the latter with Windows Task Scheduler if unattended due-time dispatch is needed.

## Optional n8n compatibility

The existing n8n workflows remain available for compatibility, but the approved scheduler workflow should stay inactive when the desktop scheduler is enabled. Never run both schedulers against the same ledger.
