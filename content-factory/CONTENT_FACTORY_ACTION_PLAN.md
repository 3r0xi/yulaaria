# Yula Aria Local Content Operations Plan

Updated: 2026-08-03

## Active architecture

```text
Compact content job
  -> stock video/photo search and download
  -> source, creator, license, and hash evidence
  -> production-specific Kie/Suno request when custom music is appropriate
  -> local audio download and rhythm/onset analysis
  -> editing-style selection using theme, assets, and recent history
  -> local Python + FFmpeg assembly
  -> silent master + original-music master + cover + preview + manifest + metadata
  -> existing human review/approval process
  -> SQLite approved schedule ledger
  -> local platform API adapters
  -> temporary R2 final-media delivery when a public URL is required
  -> permanent Google Drive archive
```

Notion remains editorial reference only. n8n and Cloud Run are outside the active execution path.

## Completed foundations

- [x] Local content factory, Pexels caching, license evidence, hashing, metadata, FFmpeg rendering, and QA.
- [x] Day-duration curve and two-Shorts structure.
- [x] Procedural ASMR score and rhythm-linked edit cues.
- [x] Kie/Suno client with current-payload validation, model policy, bounded retries, polling, download, cost gate, and secret isolation.
- [x] Kie request/response/audio/metadata artifact structure and SQLite music history.
- [x] Actual-audio onset detection for cut and pattern-interrupt alignment.
- [x] Configurable editing-style library with recent-style repetition penalty.
- [x] Mixed video/photo/texture and mixed-aspect composition foundations.
- [x] SQLite scheduling ledger, digest approval, idempotency, retry cap, run history, and stale-post safety.
- [x] Windows Task Scheduler installer/remover for local daytime dispatch.
- [x] R2 temporary object records and presigned URL staging; Google Drive remains permanent.
- [x] Future `yula-content-ops` music command contract documented without creating the skill.

## Deliberate activation gates

- [ ] Configure `KIE_API_KEY` through `configure-kie.ps1`; rotate the key that was shared in chat before production use.
- [ ] Perform one approved, low-cost Kie generation and listen to every returned variation.
- [ ] Capture the applicable Kie/Suno licensing terms and account plan in the track metadata.
- [ ] Configure/test R2 credentials and add an object lifecycle rule for the delivery prefix.
- [ ] Install Google publishing dependencies and complete a private/unlisted YouTube upload test.
- [ ] Complete safe single-post Meta tests for Facebook, Instagram, and Threads.
- [ ] Review every currently approved schedule plan, then install the Windows local scheduler.
- [ ] Add TikTok API only if the account/app becomes eligible; keep it manual until verified.

## Music-production progression

1. Use instrumental, duration-controlled `V5_5` tracks for the first short-form experiments.
2. Catalogue hook strength, motif identity, edit compatibility, retention, saves, shares, and comments.
3. Version strong motifs instead of overwriting them.
4. Create a Yula music persona only from a fully completed, approved, original track.
5. Introduce vocals and lyrics only when they improve the content concept and language strategy.
6. Extend the strongest approved motifs into longer original songs later.

## Operational rule

Codex makes compact creative and architectural decisions. Repeated production, downloads, generation polling, rendering, validation, scheduling checks, and history updates run locally. An unchanged job uses the cached result and zero model tokens.
