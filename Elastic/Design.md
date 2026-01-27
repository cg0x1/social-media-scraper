# Index Definitions and Design

Using a single Asset document with a Transcript and a field is udpated results in:

Daily metric updates rewrite the whole Lucene doc
Even if you update only view_count, ES rewrites the document under the hood. If the doc contains transcript_text + transcript_lines (nested), you’re rewriting “big payload” docs constantly → more segment merges, I/O, and heap pressure.

Nested transcript_lines multiplies index cost
Nested docs are implemented as additional hidden docs. A single asset with (say) 200 lines is effectively 201 docs at index-time. That’s fine for static indexing, but painful when the parent doc is updated frequently.

refresh_interval=30s + heavy writes
30s is decent, but thousands/day is not huge by itself — what becomes huge is thousands/day × daily refresh updates × large docs.


## TikTokAsset -> TikTokAssetTranscript

Why this is the right shape

✅ 1:1 with mapping
No extra fields, no missing fields, no accidental indexing errors.

✅ Strict-safe
dynamic:false is respected; None values are stripped.

✅ Correct numeric types
offset_ms / duration_ms are float, total_ticks is long.

✅ Write-once friendly
created_at auto-populates, updated_at refreshes.

✅ Composable
Clean separation between asset metadata and transcript content.

___

## Recommendation: split “mutable asset” from “static transcript” (minimal change, maximum win)

Keep social-source-assets as the mutable asset index

Remove these fields from it:

transcript_text

transcript_lines

(optionally) subtitles / thumbnails if they’re large blobs you don’t query

Keep only:

has_transcript (boolean)

transcript_langs (keyword array) or transcript_lang (keyword)

transcript_hashes (keyword) if you use it for change detection

This makes asset docs small and cheap to update daily.

Create a new index: social-asset-transcripts

Store transcripts once, never update (or update rarely).

Two good shapes:

A) One doc per asset (simplest)

_id = asset_id

fields:

asset_id (keyword)

channel_id / uploader_id (keyword) if you filter by these

timestamp / upload_date (date) for date filters

transcript_lang (keyword)

transcript_text (text)

transcript_lines (nested) only if you really need line-level queries

B) One doc per transcript line (best for timestamp hit / but more docs)
Only choose this if you truly need “jump to moment” behavior at scale.

Given your current mapping already uses nested lines, I’d still prefer A and keep transcript_lines optional.