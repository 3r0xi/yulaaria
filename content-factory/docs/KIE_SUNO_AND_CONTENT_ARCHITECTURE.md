# Yula Aria Local Content and Music Architecture

Status: implemented foundation; future `yula-content-ops` skill remains design-only.

## Operating boundary

- Production, approval, scheduling, and history run locally through Python, FFmpeg, SQLite, and Windows Task Scheduler.
- The current folder/metadata approval process is unchanged. Notion is not an approval dashboard.
- Google Drive is the permanent archive through `YULA_CONTENT_ROOT`.
- Cloudflare R2 is temporary final-media delivery storage only. Use content-addressed object keys, short presigned GET URLs, and a bucket lifecycle rule. Do not archive source projects in R2.
- n8n and Cloud Run are not part of the active publishing path.
- All provider secrets stay outside request JSON, manifests, logs, and Git. `KIE_API_KEY` is read from the environment first; the existing encrypted local vault remains a compatible fallback.

## Current Kie/Suno API contract

Official documentation reviewed on 2026-08-03:

- Base URL: `https://api.kie.ai`
- Generate: `POST /api/v1/generate`
- Status/result: `GET /api/v1/generate/record-info?taskId=...`
- Extend: `POST /api/v1/generate/extend`
- Lyrics: `POST /api/v1/lyrics`
- Timestamped lyrics: `POST /api/v1/generate/get-timestamped-lyrics`
- Persona: `POST /api/v1/generate/generate-persona`
- Sounds: `POST /api/v1/generate/sounds`
- Authentication: `Authorization: Bearer ...`; authentication is never part of a JSON payload.
- Generation is asynchronous. Poll no faster than the documented three queries per second per task; the local default is every 30 seconds.
- Generated music files are documented as retained for 14 days, so successful assets are downloaded immediately.
- Generation states: `PENDING`, `TEXT_SUCCESS`, `FIRST_SUCCESS`, `SUCCESS`, `CREATE_TASK_FAILED`, `GENERATE_AUDIO_FAILED`, `CALLBACK_EXCEPTION`, `SENSITIVE_WORD_ERROR`.
- Retry transient network, HTTP 408/429/5xx, and documented retryable generation failures with bounded exponential backoff. Do not retry validation, authentication, credit, or sensitive-content failures blindly.

Custom-mode limits currently documented by Kie are 3,000 prompt/200 style characters for `V3_5` and `V4`, and 5,000 prompt/1,000 style characters for the V4.5/V5 families; Generate Music titles are limited to 80 characters. The implementation validates these limits before any network request.

The wider documented capability map includes upload-and-cover, upload-and-extend, add instrumental, add vocals, stem separation, timestamped lyrics, MIDI conversion, section replacement, mashup, cover generation, WAV conversion, and music-video generation. These are recorded as future operations, not exposed as production commands yet. Extension must preserve model compatibility with its source; Persona creation requires a completed source task above V3.5 and each audio ID can create a Persona only once. Sounds generation exposes loop, tempo, and key controls and is a candidate for future ambience/SFX work, separate from the primary full-music request.

References:

- https://docs.kie.ai/suno-api/quickstart
- https://docs.kie.ai/suno-api/generate-music
- https://docs.kie.ai/suno-api/get-music-details
- https://docs.kie.ai/suno-api/generate-music-callbacks
- https://docs.kie.ai/suno-api/extend-music
- https://docs.kie.ai/suno-api/generate-persona

## Model-selection policy

The model is selected for the job, not by release date alone.

| Need | Default | Reason |
|---|---|---|
| Exact Reel/Short duration | `V5_5` | Current generate documentation says `duration` is only effective for `V5_5`. |
| Balanced quality and speed without exact duration | `V5` | General musicality/speed choice; local FFmpeg can trim or loop. |
| Richer experimental sound design | `V4_5PLUS` | Used when richness and creative variation matter more than exact duration. |
| Speed-priority exploration | `V4_5ALL` | Used for fast ideation before a production generation. |
| Vocal-focused compatibility experiment | `V4` | Optional controlled comparison, not an automatic default. |

An explicit model is respected only when compatible with the requested controls. A duration-critical request using another model fails validation instead of silently ignoring duration.

## Yula music identity

The initial sound is original cinematic electronic music with deep controlled rhythm, atmospheric tension, organic instrumental touches, tactile/ASMR detail, and reusable melodic motifs. The first 0.5-2 seconds must contain a musical hook. Energy, orchestration, and harmony should follow the content narrative rather than act as generic background.

High-level references may describe qualities such as dramatic electronic beats or organic instrumentation. Prompts must never request imitation of a named track, melody, arrangement, or signature composition. Strong motifs can be catalogued, versioned, tested against audience response, and later extended into original full-length works.

## Production request lifecycle

1. Build a creative music brief from theme, audience, platform, duration, visual hook, narrative beats, emotional arc, and desired ending.
2. Select the model using the policy above.
3. Build and validate an API-only request. Keep authentication separate.
4. Save the exact request before any network call.
5. Require both `music.generate=true` and `YULA_KIE_LIVE=1` before a billable submission.
6. Store task ID and `submitted` state in SQLite.
7. Poll every 30 seconds or accept a verified callback later. Polling is the local default because no public callback service is required.
8. Download the selected variation immediately; preserve all returned variations in response metadata.
9. Store request, response, audio, model/version, IDs, duration, hash, creative notes, licensing notes, content ID, version, and usage history.
10. Analyze the audio locally, normalize loudness, match exact export duration, and align edits to the planned or detected musical structure.

## Production-ready request example

This payload contains no secret and is valid for the current Generate Music endpoint:

```json
{
  "customMode": true,
  "instrumental": true,
  "model": "V5_5",
  "title": "Yula Night Window 01",
  "style": "cinematic electronic, atmospheric tension resolving into calm confidence, medium rising energy, warm synth bass, frame drum, airy plucks, 96 BPM, hook within 0.8 seconds",
  "prompt": "Original short-form score with an immediate musical hook, a controlled build, one memorable motif, and a loop-friendly tail.",
  "negativeTags": "recognizable melodies, generic corporate music, harsh clipping, excessive vocals",
  "styleWeight": 0.75,
  "weirdnessConstraint": 0.35,
  "audioWeight": 0.65,
  "duration": 20
}
```

The content brief may contain richer planning fields, but `build_generate_payload()` emits only current API parameters.

## Project structure and reproducibility

Each content item uses the existing daily folder and gains these structured artifacts:

```text
daily-folder/
  brief/
  scripts/
  music/
    requests/
    responses/
    audio/
    metadata/
  sources/                 # videos, photos, textures, and license evidence
  overlays/
  edit-config/
  previews/
  exports/
  metadata.txt
  manifest.draft.json
  manifest.json
```

`manifest.json` remains the canonical project manifest. It connects source URLs, licenses, hashes, music requests/results, selected editing style, rhythm cues, overlays, export settings, QA, and final outputs. SQLite stores cross-project history; it does not replace the portable manifest.

## Editing-style system

`config/editing_styles.json` contains named styles and reusable profiles. Selection considers theme keywords, available photos/videos/textures, platform, and recent style history. It penalizes recent reuse and uses a deterministic tie-break, so variation is intentional and reproducible rather than random.

Every resolved style defines shot length, transitions, motion, captions, typography, hook, music synchronization, photo/video balance, color treatment, and ending/loop strategy. A project can explicitly override the automatic style.

The local renderer supports vertical cover, contained composition on a neutral canvas, contained composition over a blurred background, and controlled photo pan/zoom. Horizontal material is not automatically destroyed by a vertical crop. The clean silent master is always preserved, while the music master is duration-matched, faded, normalized, and validated separately.

## Local SQLite scheduler

SQLite is a durable ledger, not a server. The computer does not need to be on merely to retain data. Windows Task Scheduler runs a short dispatcher every five minutes while the user is signed in, between configurable active hours. If the computer was off, `StartWhenAvailable` resumes the dispatcher. Posts more than the configured catch-up window late are marked `manual_required`; they are never published stale without review.

Install only after reviewing active approved plans:

```powershell
.\install-local-scheduler.ps1 -EveryMinutes 5 -StartHour 6 -ActiveHours 18 -CatchUpMinutes 120
```

The task can be removed with `remove-local-scheduler.ps1`. Scheduling remains digest-approved and idempotent. Provider submission, not SQLite, performs the actual platform action.

## R2 and Drive lifecycle

- Upload only approved final media needed by a provider URL.
- Use a content-addressed object key and a presigned GET URL.
- Treat the URL as a bearer token and keep its expiry short.
- Record the staged object in SQLite.
- Configure an R2 lifecycle rule for the delivery prefix; lifecycle deletion is preferable to permanent storage.
- Keep originals, manifests, API records, licenses, and exports in Google Drive permanently.
- A future cleanup command must default to dry-run and require exact object confirmation before deletion.

Cloudflare references:

- https://developers.cloudflare.com/r2/api/s3/presigned-urls/
- https://developers.cloudflare.com/r2/buckets/object-lifecycles/

## Future `yula-content-ops` command design (not implemented)

The future skill should translate operator intent into validated local project changes; it must not hold secrets or bypass approvals.

| Command | Planned behavior |
|---|---|
| `/music-create` | Build brief, select model, validate request, optionally submit after approval. |
| `/music-instrumental` | Force instrumental generation with hook/duration controls. |
| `/music-with-lyrics` | Validate language, structure, lyrics, vocal type, and disclosure needs. |
| `/music-remix` | Create an original transformation only from authorized source audio. |
| `/music-extend` | Extend a completed compatible model/audio pair. |
| `/music-variation` | Create versioned alternatives while preserving the parent record. |
| `/music-status` | Read SQLite and refresh Kie status without resubmitting. |
| `/music-download` | Download a selected completed asset immediately and hash it. |
| `/music-library` | Search motifs, versions, uses, performance, and licensing notes. |
| `/music-attach` | Attach a selected asset to a content manifest and edit configuration. |
| `/music-regenerate` | Create a new version; never overwrite or lose the previous request/result. |

Controls: model, title, genre, mood, style, tempo, energy, instrumentation, vocal type, language, lyrics, structure, hook timing, target duration, fades, variation count, output format, associated content, persona, and any future reproducibility setting actually supported by the current API. Unsupported controls such as a seed must remain local planning metadata and must never be sent as invented API fields.

## Remaining deliberate gates

- No billable Kie generation has been made during implementation.
- No Windows scheduled task is installed automatically by source changes.
- No R2 lifecycle or object deletion is executed automatically.
- No future skill or slash command is created yet.
- Licensing/usage rights must be captured from the account/service terms applicable at generation time; the API response alone must not be treated as a license grant.
