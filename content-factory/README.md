# Yula Aria Content Factory 0.4.1

This is a local-first Python worker for reproducible production and approval-gated publishing. A compact file in `jobs/` drives stock download, evidence, overlays, procedural or Kie/Suno music, configurable FFmpeg editing, metadata, hashing, and QA. Codex and desktop scripts orchestrate it locally; n8n is optional compatibility tooling.

## Safety contract

- Production remains approval-gated and inactive by default.
- Every downloaded asset needs a saved source URL, creator, license type, license check date, and SHA-256 hash.
- “Royalty-free” is not the same as “copyright-free.” External audio is accepted only with a recorded CC0/public-domain or explicit commercial-use license.
- Procedural audio never accepts a named artist, named song, or imitation prompt. Its JSON score and seed make the output reproducible.
- Kie/Suno authentication is loaded from `KIE_API_KEY`; requests, manifests, logs, and Git never contain it. A billable request requires `music.generate=true` and `YULA_KIE_LIVE=1`.
- A clean no-music video master is always preserved.
- Existing approved exports are never overwritten unless `--force` is explicitly supplied.

## Commands

```powershell
$py = 'C:\Users\ercan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\python.exe'
& $py -m unittest discover -s tests -v
& $py -m yula_factory.cli init-db
& $py -m yula_factory.cli audio --score examples\day01_audio_score.json --output day01_original.wav
& $py -m yula_factory.cli run-photo-gallery --job photo_galleries\day01.json
& $py -m yula_factory.cli duration-target --day 20
& $py -m yula_factory.cli buffer-validate-plan --plan examples\buffer_schedule_plan.example.json
& $py -m yula_factory.cli serve --host 127.0.0.1 --port 8765
```

The shortest path from VS Code or PowerShell is:

```powershell
.\configure-secrets.ps1  # one time; secure prompts, no .env file
.\configure-kie.ps1      # one time; stores KIE_API_KEY in the Windows user environment
.\copy-n8n-token.ps1     # copies the worker Bearer value without printing it
.\run.ps1 test
.\run.ps1 validate-job --job jobs\day02.json
.\run.ps1 run-job --job jobs\day02.json
.\run.ps1 run-photo-gallery --job photo_galleries\day01.json
.\run.ps1 unify-metadata --folder "G:\My Drive\Codex_n8n\Yula Aria\Content Sharing Plan\2026-08-01_D01_..."
.\configure-buffer.ps1  # optional; stores BUFFER_API_KEY in the Windows user environment
.\start-free-media-tunnel.ps1  # starts the zero-cost signed HTTPS media bridge
```

An unchanged completed job returns `status: cached`; it does not redownload, rerender, or use Codex tokens. See `TOKEN_SAVING_ARCHITECTURE.md`.

For the second daily YouTube Short, run a second job for the same day with `"content_slot": "youtube_companion"` and a unique `output_stem`. Its sources and technical records remain separate, while its publishing copy is inserted into the day's single metadata file.

To create a small Pexels candidate index for a future day:

```powershell
.\run.ps1 pexels-search --query "window reflection city" --output candidates\day03.json
```

Photo-gallery jobs use the Pexels Photo API, save the selected API records in each daily folder, download source images with license evidence, and export subtle editorial crops/retouches in `exported photos\instagram_facebook_4x5` and `exported photos\tiktok_9x16`. Video and photo copy is combined under separate headings in the day's single `metadata.txt`; originals are backed up during migration.

Scheduling remains inactive by default. The cross-platform ledger supports Meta, YouTube, Buffer, and TikTok Content Posting API Direct Post with exact-digest approval and idempotency protection. TikTok has no native future-post parameter, so the local dispatcher uploads the approved item when its SQLite due time arrives. See `PUBLISHING_AUTOMATION_SETUP.md`.

The local SQLite dispatcher can be installed as a Windows scheduled task after active plans are reviewed:

```powershell
.\install-local-scheduler.ps1 -EveryMinutes 5 -StartHour 6 -ActiveHours 18 -CatchUpMinutes 120
```

The task runs briefly while the user is signed in; SQLite itself is not a background server. Late posts outside the catch-up window are moved to manual review instead of being published stale.

The default Meta media bridge uses a local HMAC-signed URL exposed through a free, temporary Cloudflare Quick Tunnel. Start it before live dispatch; the computer must remain online while Meta ingests the file:

```powershell
powershell.exe -NoProfile -ExecutionPolicy Bypass -File .\start-free-media-tunnel.ps1
```

Cloudflare R2 is the optional temporary final-media delivery bridge. It uses content-addressed objects and bounded signed URLs; Google Drive remains the permanent archive:

```powershell
.\run.ps1 r2-stage --file "..\2026-08-10_D10_...\exports\reel.mp4" --publishing-day 2026-08-10 --expires-hours 48
```

When running directly from the checkout, set `PYTHONPATH` to the `src` folder or use the included `run.ps1`.

The Kie/Suno model policy, request lifecycle, music identity, editing-style library, artifact layout, and future skill command contract are documented in `docs/KIE_SUNO_AND_CONTENT_ARCHITECTURE.md`. The future `yula-content-ops` skill has intentionally not been created.

The HTTP worker exposes:

- `GET /health`
- `POST /v1/audio/generate`
- `POST /v1/qa/folder`
- `POST /v1/errors/log`
- `POST /v1/jobs/run` with `{ "job_path": "...\\_factory\\jobs\\day02.json" }`
- `POST /v1/schedule/plan`
- `POST /v1/schedule/approve`
- `POST /v1/schedule/dispatch-due`
- `POST /v1/schedule/status`

Set `YULA_FACTORY_TOKEN` before starting the server. Send the same value in `Authorization: Bearer ...`. Codex calls the worker through `http://127.0.0.1:8765`; optional Docker/n8n clients use `http://host.docker.internal:8765`. Media remains on disk and requests contain JSON paths only.
