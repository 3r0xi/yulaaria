# Yula Aria Publisher Website

Public static website for the Yula Aria Publisher service, including the pages required by third-party platform developer reviews.

## Pages

- `/` — official website
- `/privacy.html` — Privacy Policy
- `/terms.html` — Terms of Service
- `/data-deletion.html` — data deletion instructions

## TikTok URL verification

When TikTok supplies a URL-prefix verification file, place the supplied file at the repository root without altering its filename or contents, then redeploy. Verify the exact published URL prefix in TikTok’s Developer Portal.

## Local content automation

`content-factory/` contains the local, approval-gated production and SQLite scheduling system. Its TikTok provider uses the official Content Posting API Direct Post flow and uploads an approved local video only when the desktop dispatcher reaches its due time. Credentials and generated media are deliberately excluded from Git; local secrets are stored in a Windows DPAPI vault.
