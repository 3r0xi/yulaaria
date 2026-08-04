# Duration, Audio, and Scheduling Policy

## Reel duration curve

Day 10 remains 15 seconds. Day 11 starts at 17 seconds and the target grows by two or three seconds per day until Day 30 reaches 70 seconds. The job validator allows a three-second editorial tolerance.

Longer renders must not be padded. Use a hook in the first two seconds, a visual or text change every four to seven seconds, a mid-video turn, and a closing loop or question. The duration curve is implemented in `src/yula_factory/duration.py`.

## Original ASMR audio

The procedural WAV generator now supports seven restrained theme profiles: soft room, rain on glass, coffee room, coastal air, architecture clicks, travel rumble, and hotel hum. The job theme selects the default profile; a job may override it with `audio_score.asmr_profile`. All output is locally generated, deterministic, and does not imitate a named song or artist.

From Day 11 onward, the factory derives cut points, crossfade starts, and subtle visual pattern interrupts from the same BPM and deterministic seed as the ASMR score. A rhythm cue JSON is saved beside the audio so the relationship can be audited and reproduced. Set `render.audio_sync.enabled` to `false` only when an edit needs a deliberate manual exception.

No external Python package or Codex skill is required.

## Kie/Suno original music

When a content concept benefits from a bespoke professional score, the job may use `music.provider: kie_suno` instead of the procedural generator. Duration-critical short-form requests select `V5_5` because the current Kie documentation limits the `duration` parameter to that model. The exact request is saved before submission, and a billable call requires both `music.generate=true` and `YULA_KIE_LIVE=1`.

After download, the local pipeline converts the selected audio to analysis PCM, detects useful energy onsets, and snaps planned cuts and pattern interrupts to nearby accents. FFmpeg then loops or trims safely to the exact visual duration, applies short fades, and normalizes the master. The silent master is always retained.

## Two YouTube Shorts per day

From Day 11 onward, produce:

1. The main cross-platform vertical video.
2. A YouTube-only companion Short using a different hook, source order, cover text, and closing question.

The companion should add real editorial value rather than being a duplicate. Schedule the two Shorts at least six hours apart. Both entries belong under the `VIDEO / REEL` heading in the day's single `metadata.txt`.

Set `content_slot` to `youtube_companion` in the second job. The factory then uses separate source, overlay, audio, manifest, QA, state, and export names while inserting the approved YouTube copy into the same daily metadata file.

## Scheduling gate

Buffer is the preferred calendar and queue view. The local Buffer client validates a JSON plan first and refuses submission unless `--approve` is present. Running the command still requires an explicit user instruction to schedule.

Secrets must not be stored in this Google Drive folder or committed to Git. Run `configure-buffer.ps1`; it stores `BUFFER_API_KEY` in the Windows user environment. Media URLs used by the Buffer API must be publicly accessible HTTPS URLs. Local Google Drive paths are not uploaded automatically.

The production scheduler is local SQLite plus a short Windows scheduled task, not an always-running database server. A configurable catch-up window handles brief downtime; older missed posts move to manual review instead of being published late. R2 can temporarily host approved final media for Meta ingestion, while Google Drive remains the permanent archive.

TikTok photo posts can be prepared in Buffer's web interface. The current Buffer `createPost` API documentation does not list TikTok as a supported creation service, so the local API client rejects TikTok plans instead of pretending they will work.
