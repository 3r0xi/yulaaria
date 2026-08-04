# Low-token operating model

The expensive creative decision is reduced to one compact file in `jobs/`. Everything after that is local and deterministic:

1. Python reads the day job.
2. Pexels files are downloaded with retries and cached on disk.
3. Creator, source, license evidence, and SHA-256 records are generated locally.
4. Text overlays and the cover are generated from the job.
5. The configured local procedural score is synthesized, or an approved Kie/Suno request is generated, polled, downloaded, and cached locally.
6. Local onset analysis aligns cuts and pattern interrupts before FFmpeg creates the silent master, original-audio master, cover, and contact sheet.
7. Technical QA checks codec, dimensions, duration, audio, hashes, and required files.
8. `run_state.json` caches the completed job hash, so an unchanged rerun does no work.

## When Codex is used

- Draft or improve the small day-job brief.
- Review a contact sheet when visual judgment is useful.
- Diagnose a short sanitized error after local retries fail.
- Review weekly performance metrics and approve strategy changes.

Never send raw videos, full logs, the workbook, or the whole Notion database to a model for routine production. A normal local run reports `codex_tokens_used_by_local_run: 0`.

## Secret boundary

Pexels, Kie, publishing, R2, and worker keys are read from Windows user environment variables or the encrypted local provider vault. They never belong in a job, manifest, workflow, log, or Git repository. Run the matching secure configuration script once and open a new terminal.

## Git boundary

A future private repository should contain `_factory` code, tests, templates, and compact jobs. Keep downloaded media, exports, SQLite state, logs, and secrets out of Git. The included `.gitignore` enforces this inside the factory repository.
