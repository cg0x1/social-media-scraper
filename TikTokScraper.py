from __future__ import annotations

import re
from datetime import datetime, timezone
import requests
from typing import Any, Dict, List, Optional, Tuple
from elasticsearch7 import Elasticsearch, helpers
from yt_dlp import YoutubeDL
from AssetTranscriptLine import AssetTranscriptLine
from TikTokAssetMapper import TikTokAssetMapper, TikTokAssetMapperOptions


class TikTokScraper:
    """
    A complete TikTok scraper that:
      - Crawls newest->oldest (default), with hard caps
      - Stops once it hits a known timestamp (state stored in Elasticsearch as ISO UTC date)
      - Backfills older history safely using a moving cutoff (also in Elasticsearch)
      - Detects suspicious/silently truncated pagination via run-quality heuristics
      - Minimizes network calls via conditional hydration:
          * Pass A: inventory (extract_flat=True) -> cheap list of video URLs/IDs
          * Pass B: hydrate only what is needed (newest since known_ts or older than cutoff)
      - Enriches hydrated videos with transcripts (VTT/SRT) and structured lines
      - NEW: Saves newly discovered TikTokAssets into Elasticsearch `tiktok-asset` index,
        mirroring your TikTokAsset class/mapping (including stored-only `raw` and `subtitles`).

    Notes:
      - yt-dlp returns video["timestamp"] as epoch seconds (int).
      - Elasticsearch 'timestamp' field is stored as ISO UTC date (e.g. 2026-01-25T14:12:00Z).
        This class keeps state in ISO, compares using epoch seconds in-memory,
        and writes asset docs with `timestamp` as ISO UTC string.
    """
    
    def __init__(self, *, hash_len: int = 32):
        self.asset_mapper = TikTokAssetMapper(TikTokAssetMapperOptions(hash_len=hash_len))


    # -----------------------------
    # Constants / Regex
    # -----------------------------
    TICKS_PER_MS = 10_000
    TIMECODE_RE = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
    )

    # -----------------------------
    # Elasticsearch Index Names
    # -----------------------------
    DEFAULT_STATE_INDEX = "tiktok-crawl-state"
    DEFAULT_ASSET_INDEX = "tiktok-assets"

    # -----------------------------
    # ISO / epoch helpers
    # -----------------------------
    @staticmethod
    def _now_utc_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def epoch_to_iso_utc(ts_seconds: int) -> str:
        return datetime.fromtimestamp(int(ts_seconds), tz=timezone.utc).isoformat().replace("+00:00", "Z")

    @staticmethod
    def iso_utc_to_epoch(iso_str: str) -> int:
        # Accepts "Z" or "+00:00"
        dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
        return int(dt.timestamp())

    # -----------------------------
    # Elasticsearch state management
    # -----------------------------
    @classmethod
    def state_doc_id(cls, platform: str, profile: str) -> str:
        return f"{platform}:{profile}"

    @classmethod
    def ensure_state_index(cls, es: Elasticsearch, state_index: str = DEFAULT_STATE_INDEX) -> None:
        if es.indices.exists(index=state_index):
            return
        es.indices.create(
            index=state_index,
            mappings={
                "properties": {
                    "platform": {"type": "keyword"},
                    "profile": {"type": "keyword"},
                    "profile_url": {"type": "keyword"},
                    "known_timestamp_iso": {"type": "date"},
                    "backfill_cutoff_iso": {"type": "date"},
                    "last_run": {"type": "object", "enabled": True},
                }
            },
        )

    @classmethod
    def load_state(
        cls,
        es: Elasticsearch,
        *,
        platform: str,
        profile: str,
        profile_url: str,
        state_index: str = DEFAULT_STATE_INDEX,
    ) -> Dict[str, Any]:
        doc_id = cls.state_doc_id(platform, profile)
        try:
            resp = es.get(index=state_index, id=doc_id)
            src = resp.get("_source") or {}
            # Ensure required keys exist
            src.setdefault("platform", platform)
            src.setdefault("profile", profile)
            src.setdefault("profile_url", profile_url)
            src.setdefault("known_timestamp_iso", None)
            src.setdefault("backfill_cutoff_iso", None)
            src.setdefault("last_run", None)
            return src
        except Exception:
            # First run default state
            return {
                "platform": platform,
                "profile": profile,
                "profile_url": profile_url,
                "known_timestamp_iso": None,
                "backfill_cutoff_iso": None,
                "last_run": None,
            }

    @classmethod
    def save_state(
        cls,
        es: Elasticsearch,
        state: Dict[str, Any],
        *,
        state_index: str = DEFAULT_STATE_INDEX,
    ) -> None:
        doc_id = cls.state_doc_id(state.get("platform", "tiktok"), state.get("profile", ""))
        es.index(index=state_index, id=doc_id, document=state, refresh=False)

    # -----------------------------
    # TikTokAsset doc building + saving
    # -----------------------------
    @staticmethod
    def _asset_id_from_video_id(video_id: str) -> str:
        # Deterministic system ID to prevent duplicates
        return f"tiktok:{video_id}"

    @staticmethod
    def _pick_thumbnail(e: Dict[str, Any]) -> Optional[str]:
        t = e.get("thumbnail")
        if isinstance(t, str) and t:
            return t
        thumbs = e.get("thumbnails")
        if isinstance(thumbs, list):
            for th in thumbs:
                if isinstance(th, dict) and th.get("url"):
                    return th["url"]
        return None

    @staticmethod
    def _flatten_artists(e: Dict[str, Any]) -> Optional[str]:
        # Best-effort: you can customize later.
        # Many TikTok extracts don’t have a consistent "artists" list; we opportunistically combine a few fields.
        candidates: List[str] = []
        for k in ("artists", "artist", "creator", "uploader"):
            v = e.get(k)
            if isinstance(v, list):
                candidates.extend([str(x).strip() for x in v if x])
            elif isinstance(v, str) and v.strip():
                candidates.append(v.strip())

        # stable de-dupe
        out: List[str] = []
        seen = set()
        for x in candidates:
            if x and x not in seen:
                out.append(x)
                seen.add(x)
        return ";".join(out) if out else None

    def build_tiktok_asset_doc(self, e: Dict[str, Any]) -> Dict[str, Any]:
        """
        Build an ES document that mirrors your TikTokAsset class and matches the `tiktok-asset` mapping.

        Important:
          - Writes `timestamp` as ISO UTC string because ES field type is `date`.
          - Stores `raw` and `subtitles` as stored-only blobs.
          - Uses `asset_id = tiktok:{id}`.
        """
        video_id = str(e.get("id") or "").strip()
        if not video_id:
            # if yt-dlp didn't provide a stable id, skip (can't dedupe safely)
            return {}

        # timestamp in ES is `date`, so store ISO UTC
        ts_epoch = e.get("timestamp")
        ts_iso = None
        if isinstance(ts_epoch, (int, float)) and ts_epoch:
            ts_iso = self.epoch_to_iso_utc(int(ts_epoch))
        elif isinstance(ts_epoch, str) and ts_epoch:
            # If someone already converted it upstream
            ts_iso = ts_epoch

        # transcript_lines: your enrichment already uses list[dict] with correct keys
        transcript_lines = e.get("transcript_lines") or []
        if not isinstance(transcript_lines, list):
            transcript_lines = []

        # stored-only subtitles blob (your mapping: enabled:false)
        subtitles_blob = None
        if "requested_subtitles" in e:
            subtitles_blob = e.get("requested_subtitles")
        elif "subtitles" in e:
            subtitles_blob = e.get("subtitles")
        elif "automatic_captions" in e:
            subtitles_blob = e.get("automatic_captions")

        doc: Dict[str, Any] = {
            "asset_id": self._asset_id_from_video_id(video_id),
            "id": video_id,
            "display_id": e.get("display_id"),
            "channel": e.get("channel"),
            "channel_id": e.get("channel_id"),
            "uploader": e.get("uploader"),
            "uploader_id": str(e.get("uploader_id")) if e.get("uploader_id") is not None else None,
            "playlist": e.get("playlist"),
            "playlist_id": e.get("playlist_id"),
            "playlist_title": e.get("playlist_title"),
            "title": e.get("title"),
            "description": e.get("description"),
            "artists": self._flatten_artists(e),
            "view_count": e.get("view_count"),
            "like_count": e.get("like_count"),
            "comment_count": e.get("comment_count"),
            "repost_count": e.get("repost_count"),
            "upload_date": e.get("upload_date"),
            "transcript_lang": e.get("transcript_lang"),
            "transcript_text": e.get("transcript_text"),
            "transcript_lines": transcript_lines,
            "duration": e.get("duration"),
            "timestamp": ts_iso,  # ES date
            "track": e.get("track"),
            "webpage_url": e.get("webpage_url"),
            "original_url": e.get("original_url"),
            "channel_url": e.get("channel_url"),
            "uploader_url": e.get("uploader_url"),
            "playlist_webpage_url": e.get("playlist_webpage_url"),
            "thumbnail": self._pick_thumbnail(e),
            "subtitles": subtitles_blob,  # stored-only
        }
        
        self.asset_mapper.enrich_asset_doc_inplace(doc)

        # Drop None values (optional; keeps docs smaller)
        return {k: v for k, v in doc.items() if v is not None}

    def save_new_assets(
        self,
        *,
        es: Elasticsearch,
        videos: List[Dict[str, Any]],
        asset_index: str = DEFAULT_ASSET_INDEX,
        refresh: bool = False,
    ) -> Dict[str, Any]:
        """
        Save only NEW TikTokAssets to ES by using bulk op_type='create'.
        Existing docs (same _id) are not overwritten; conflicts are ignored.

        Returns summary with created/conflicts/errors counts.
        """
        actions = []
        for v in videos:
            doc = self.build_tiktok_asset_doc(v)
            if not doc:
                continue
            actions.append({
                "_op_type": "create",
                "_index": asset_index,
                "_id": doc["asset_id"],
                "_source": doc
            })

        if not actions:
            return {"attempted": 0, "created": 0, "conflicts": 0, "errors": 0}

        # We want to tolerate 409 conflicts (already exists). helpers.bulk treats those as errors unless we parse.
        # So we use streaming_bulk and count statuses explicitly.
        created = 0
        conflicts = 0
        errors = 0
        attempted = 0

        for ok, item in helpers.streaming_bulk(
            es,
            actions,
            raise_on_error=False,
            raise_on_exception=False,
            yield_ok=True,
        ):
            attempted += 1
            # item looks like {"create": {"_index":..., "_id":..., "status":..., "error":...}}
            op = item.get("create") or item.get("index") or item.get("update") or {}
            status = op.get("status")

            if ok and status in (200, 201):
                created += 1
            elif status == 409:
                conflicts += 1
            else:
                errors += 1

        if refresh:
            es.indices.refresh(index=asset_index)

        return {"attempted": attempted, "created": created, "conflicts": conflicts, "errors": errors}

    # -----------------------------
    # Pagination / run-quality heuristics
    # -----------------------------
    @staticmethod
    def assess_pagination(
        *,
        requested_inventory: int,
        inventory_entries: List[Dict[str, Any]],
        hydrated_success: int,
        hydrated_errors: int,
        hydrated_timestamps: List[int],
    ) -> Dict[str, Any]:
        ids = [e.get("id") for e in inventory_entries if e.get("id")]
        inv_count = len(ids)

        dup_rate = 0.0
        if ids:
            dup_rate = 1.0 - (len(set(ids)) / max(1, len(ids)))

        # timestamp disorder (newest->oldest should be mostly decreasing; pinned vids can disrupt)
        disorder = 0
        ts = [t for t in hydrated_timestamps if t]
        if len(ts) >= 2:
            disorder = sum(1 for a, b in zip(ts, ts[1:]) if b > a)

        flags: List[str] = []

        # short inventory often indicates silent truncation / early stop upstream
        if inv_count < int(requested_inventory * 0.8):
            flags.append(f"short_inventory:{inv_count}/{requested_inventory}")

        # duplicates indicate pagination glitch
        if dup_rate > 0.05:
            flags.append(f"dup_rate:{dup_rate:.1%}")

        # high hydration error rate indicates blocking / intermittent failures
        attempted = hydrated_success + hydrated_errors
        if attempted > 0:
            err_rate = hydrated_errors / attempted
            if err_rate > 0.2:
                flags.append(f"high_error_rate:{err_rate:.1%}")

        # too much disorder is suspicious (beyond a little pinned-content noise)
        if disorder > 3:
            flags.append(f"timestamp_disorder:{disorder}")

        if not flags:
            flags.append("ok")

        return {
            "requested_inventory": requested_inventory,
            "inventory_count": inv_count,
            "duplicate_rate": dup_rate,
            "timestamp_disorder": disorder,
            "hydrated_attempted": hydrated_success + hydrated_errors,
            "hydrated_success": hydrated_success,
            "hydrated_errors": hydrated_errors,
            "flags": flags,
        }

    # -----------------------------
    # 1) caption URL extraction
    # -----------------------------
    def get_transcript_urls_by_language(
        self,
        info: Dict[str, Any],
        *,
        prefer_requested: bool = True,
        exts: Optional[set[str]] = None,
        proxy_address: str,  # kept for signature compatibility; not used directly here
    ) -> Dict[str, List[Dict[str, str]]]:
        if exts is not None:
            exts = {e.lower().lstrip(".") for e in exts}

        out: Dict[str, List[Dict[str, str]]] = {}

        def add_track(lang: str, track: Dict[str, Any], source: str) -> None:
            url = track.get("url")
            if not url:
                return
            ext = (track.get("ext") or "").lower().lstrip(".")
            if exts is not None and ext not in exts:
                return
            item: Dict[str, str] = {"ext": ext or "", "url": url, "source": source}
            name = track.get("name") or track.get("title")
            if name:
                item["name"] = str(name)
            out.setdefault(lang, []).append(item)

        requested = info.get("requested_subtitles") or {}
        if isinstance(requested, dict):
            for lang, track in requested.items():
                if isinstance(track, dict):
                    add_track(lang, track, "requested_subtitles")
            if prefer_requested and out:
                return out

        subtitles = info.get("subtitles") or {}
        if isinstance(subtitles, dict):
            for lang, tracks in subtitles.items():
                if isinstance(tracks, list):
                    for t in tracks:
                        if isinstance(t, dict):
                            add_track(lang, t, "subtitles")

        auto = info.get("automatic_captions") or {}
        if isinstance(auto, dict):
            for lang, tracks in auto.items():
                if isinstance(tracks, list):
                    for t in tracks:
                        if isinstance(t, dict):
                            add_track(lang, t, "automatic_captions")

        return out

    # -----------------------------
    # 2) download + parse caption text
    # -----------------------------
    def _download_text(self, url: str, headers: Optional[dict], proxy: Optional[str], timeout: int = 30) -> str:
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        # NOTE: verify=False is consistent with your previous usage.
        r = requests.get(url, headers=headers or {}, proxies=proxies, timeout=timeout, verify=False)
        r.raise_for_status()
        return r.text

    def _vtt_or_srt_to_text(self, s: str) -> str:
        if not s:
            return ""

        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

        lines: List[str] = []
        for line in s.split("\n"):
            line = line.strip()
            if not line:
                continue

            if re.fullmatch(r"\d+", line):
                continue

            if re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", line):
                continue
            if re.search(r"\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}\.\d{3}", line):
                continue

            if "-->" in line:
                continue

            line = re.sub(r"<[^>]+>", "", line).strip()
            if line:
                lines.append(line)

        text = " ".join(lines)
        return re.sub(r"\s+", " ", text).strip()

    def _pick_language(self, captions_by_lang: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
        preferred = ["eng-US", "eng", "en", "en-US"]
        for p in preferred:
            if p in captions_by_lang:
                return p
        return next(iter(captions_by_lang.keys()), None)

    # -----------------------------
    # Structured caption parsing (VTT/SRT -> lines)
    # -----------------------------
    def _time_to_ms(self, t: str) -> int:
        parts = t.split(":")
        if len(parts) == 3:
            h, m, rest = parts
        else:
            h = "0"
            m, rest = parts
        s, ms = rest.split(".")
        return (
            int(h) * 3600_000
            + int(m) * 60_000
            + int(s) * 1000
            + int(ms)
        )

    def parse_vtt_to_lines(self, s: str) -> List[AssetTranscriptLine]:
        """
        Best-effort VTT/SRT timecode parsing into structured lines.
        """
        if not s:
            return []

        s = s.replace("\r\n", "\n").replace("\r", "\n")

        lines_out: List[AssetTranscriptLine] = []
        current_text: List[str] = []
        start_ms: Optional[int] = None
        end_ms: Optional[int] = None

        def flush():
            nonlocal current_text, start_ms, end_ms
            if start_ms is None or end_ms is None:
                current_text = []
                start_ms = None
                end_ms = None
                return
            content = " ".join(x.strip() for x in current_text if x.strip())
            content = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", content)).strip()
            if content:
                offset = int(start_ms)
                dur = int(max(0, end_ms - start_ms))
                ticks = (offset + dur) * self.TICKS_PER_MS
                lines_out.append(
                    AssetTranscriptLine(
                        offset_ms=offset, duration_ms=dur, total_ticks=ticks, content=content
                    )
                )
            current_text = []
            start_ms = None
            end_ms = None

        # skip WEBVTT header lines
        s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

        for raw_line in s.split("\n"):
            line = raw_line.strip()

            # cue boundary
            if not line:
                flush()
                continue

            # cue index
            if re.fullmatch(r"\d+", line):
                continue

            m = self.TIMECODE_RE.search(line)
            if m:
                flush()
                start_ms = self._time_to_ms(m.group("start"))
                end_ms = self._time_to_ms(m.group("end"))
                continue

            # ignore cue settings line
            if "-->" in line:
                continue

            current_text.append(line)

        flush()
        return lines_out

    # -----------------------------
    # yt-dlp option builders
    # -----------------------------
    @staticmethod
    def _ydl_default_options(
        proxy: Optional[str],
        playlist_end: int,
        quiet: bool = True,
    ) -> Dict[str, Any]:
        # IMPORTANT CHANGE:
        # - extract_flat=True for cheap inventory (no per-video webpage download)
        return {
            "skip_download": True,
            "proxy": proxy,
            "quiet": quiet,
            "verbose": True,
            "extract_flat": True,          # full metadata, not just URLs
            "nocheckcertificate": True,
            "playlistend": playlist_end,
            "writesubtitles": True,
            "writeautomaticsubtitles": True,
            "writeinfojson": False,
            "sleep_interval": 2,
            "max_sleep_interval": 5,
            "sleep_interval_requests": 1,
            "retries": 2,
        }

    @staticmethod
    def _ydl_opts_hydrate(
        proxy: Optional[str],
        *,
        verbose: bool = True,
        retries: int = 2,
        sleep_interval: int = 2,
        max_sleep_interval: int = 5,
        sleep_interval_requests: int = 1,
        download_archive: Optional[str] = None,
        writesubtitles: bool = True,
        writeautomaticsubtitles: bool = True,
    ) -> Dict[str, Any]:
        opts = {
            "skip_download": True,
            "proxy": proxy,
            "quiet": False,
            "verbose": verbose,
            "extract_flat": False,  # full metadata
            "nocheckcertificate": True,
            "writesubtitles": writesubtitles,
            "writeautomaticsubtitles": writeautomaticsubtitles,
            "writeinfojson": False,
            "sleep_interval": sleep_interval,
            "max_sleep_interval": max_sleep_interval,
            "sleep_interval_requests": sleep_interval_requests,
            "retries": retries,
        }
        if download_archive:
            opts["download_archive"] = download_archive
        return opts

    # -----------------------------
    # Inventory: get minimal entries (id/url)
    # -----------------------------
    def inventory_playlist_entries(
        self,
        playlist_url: str,
        *,
        proxy: Optional[str] = None,
        playlist_end: int = 200,
    ) -> List[Dict[str, Any]]:
        options = self._ydl_default_options(proxy, playlist_end=playlist_end, quiet=True)

        with YoutubeDL(options) as ydl:
            info = ydl.extract_info(playlist_url, download=False)

        entries = [e for e in (info.get("entries") or []) if e]

        # Normalize to ensure url exists
        normed: List[Dict[str, Any]] = []
        for e in entries:
            url = e.get("url") or e.get("webpage_url")
            if not url:
                url = e.get("id")
            if not url:
                continue
            normed.append(
                {
                    "id": e.get("id"),
                    "url": url,
                    "webpage_url": e.get("webpage_url") or url,
                    "title": e.get("title"),
                    "extractor": e.get("extractor"),
                    "extractor_key": e.get("extractor_key"),
                }
            )

        return normed

    # -----------------------------
    # Hydrate a single video URL
    # -----------------------------
    def hydrate_video_info(
        self,
        video_url: str,
        *,
        proxy: Optional[str] = None,
        download_archive: Optional[str] = "tiktok_seen.txt",
        retries: int = 2,
    ) -> Dict[str, Any]:
        with YoutubeDL(self._ydl_opts_hydrate(proxy, retries=retries, download_archive=download_archive)) as ydl:
            return ydl.extract_info(video_url, download=False)

    # -----------------------------
    # Transcript enrichment for a hydrated video dict
    # -----------------------------
    def enrich_video_with_transcripts(
        self,
        e: Dict[str, Any],
        *,
        proxy: Optional[str],
        store_all_languages: bool,
    ) -> Dict[str, Any]:
        # Default fields
        e["transcript_text"] = ""
        e["transcript_lang"] = None
        e["transcript_lines"] = []
        e["transcript_lines_by_lang"] = {} if store_all_languages else None
        e["transcripts"] = {} if store_all_languages else None

        captions = self.get_transcript_urls_by_language(
            e, prefer_requested=False, exts={"vtt", "srt"}, proxy_address=proxy or ""
        )
        if not captions:
            return e

        headers = e.get("http_headers") or {}

        if store_all_languages:
            for lang, tracks in captions.items():
                if not tracks:
                    continue
                track = tracks[0]
                try:
                    raw = self._download_text(track["url"], headers=headers, proxy=proxy)
                    e["transcripts"][lang] = self._vtt_or_srt_to_text(raw)
                    parsed_lines = self.parse_vtt_to_lines(raw)
                    e["transcript_lines_by_lang"][lang] = [
                        {
                            "offset_ms": l.offset_ms,
                            "duration_ms": l.duration_ms,
                            "total_ticks": l.total_ticks,
                            "content": l.content,
                        }
                        for l in parsed_lines
                    ]
                except Exception as ex:
                    e["transcripts"][lang] = f"__error__: {ex}"
                    e["transcript_lines_by_lang"][lang] = []

            chosen = self._pick_language({k: v for k, v in captions.items() if v})
            if chosen:
                e["transcript_lang"] = chosen
                chosen_text = e["transcripts"].get(chosen)
                if isinstance(chosen_text, str):
                    e["transcript_text"] = chosen_text
                chosen_lines = e["transcript_lines_by_lang"].get(chosen)
                if isinstance(chosen_lines, list):
                    e["transcript_lines"] = chosen_lines
        else:
            chosen = self._pick_language(captions)
            if not chosen:
                return e
            track = captions[chosen][0]
            try:
                raw = self._download_text(track["url"], headers=headers, proxy=proxy)
                e["transcript_lang"] = chosen
                e["transcript_text"] = self._vtt_or_srt_to_text(raw)

                parsed_lines = self.parse_vtt_to_lines(raw)
                e["transcript_lines"] = [
                    {
                        "offset_ms": l.offset_ms,
                        "duration_ms": l.duration_ms,
                        "total_ticks": l.total_ticks,
                        "content": l.content,
                    }
                    for l in parsed_lines
                ]
            except Exception as ex:
                e["transcript_lang"] = chosen
                e["transcript_text"] = f"__error__: {ex}"
                e["transcript_lines"] = []

        return e

    # -----------------------------
    # Newest crawl: stop at known timestamp (ISO in ES state)
    # -----------------------------
    def crawl_newest(
        self,
        *,
        playlist_url: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 200,
        hydrate_cap: int = 30,
        known_timestamp_iso: Optional[str] = None,
        store_all_languages: bool = False,
        download_archive: str = "tiktok_seen.txt",
        retries: int = 2,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
        """
        Newest->oldest crawl:
          - Inventory cheaply (no per-video webpage)
          - Hydrate videos until:
              * we reach hydrate_cap, OR
              * we hit a video with timestamp <= known_timestamp, OR
              * we run out of inventory
          - Enrich hydrated videos with transcripts
          - Returns (videos_sorted_newest_first, run_metrics)
        """
        inventory = self.inventory_playlist_entries(playlist_url, proxy=proxy, playlist_end=inventory_limit)
        stop_epoch = self.iso_utc_to_epoch(known_timestamp_iso) if known_timestamp_iso else 0

        hydrated: List[Dict[str, Any]] = []
        hydrated_ts: List[int] = []
        errors = 0

        for item in inventory:
            if len(hydrated) >= hydrate_cap:
                break
            url = item.get("webpage_url") or item.get("url")
            if not url:
                continue

            try:
                v = self.hydrate_video_info(
                    url,
                    proxy=proxy,
                    download_archive=download_archive,
                    retries=retries,
                )

                ts = int(v.get("timestamp") or 0)

                v = self.enrich_video_with_transcripts(v, proxy=proxy, store_all_languages=store_all_languages)

                hydrated.append(v)
                hydrated_ts.append(ts)

                # Stop once we hit known timestamp
                if stop_epoch and ts and ts <= stop_epoch:
                    break

            except Exception:
                errors += 1

        hydrated_sorted = sorted(hydrated, key=lambda e: e.get("timestamp") or 0, reverse=True)

        run_metrics = self.assess_pagination(
            requested_inventory=inventory_limit,
            inventory_entries=inventory,
            hydrated_success=len(hydrated),
            hydrated_errors=errors,
            hydrated_timestamps=hydrated_ts,
        )
        run_metrics.update(
            {
                "at": self._now_utc_iso(),
                "mode": "newest",
                "known_timestamp_iso": known_timestamp_iso,
                "inventory_limit": inventory_limit,
                "hydrate_cap": hydrate_cap,
            }
        )

        return hydrated_sorted, run_metrics

    # -----------------------------
    # Backfill crawl: safely move a cutoff backward
    # -----------------------------
    def backfill_history(
        self,
        *,
        playlist_url: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 400,
        hydrate_cap: int = 50,
        backfill_cutoff_iso: Optional[str] = None,
        store_all_languages: bool = False,
        download_archive: str = "tiktok_seen.txt",
        retries: int = 2,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Optional[str]]:
        """
        Backfill older content:
          - Inventory cheaply
          - Hydrate videos older than backfill_cutoff
          - After a batch, returns a new cutoff ISO (oldest_ts_seen - 1 second) so the next run moves older.

        Returns: (videos, run_metrics, new_cutoff_iso)
        """
        inventory = self.inventory_playlist_entries(playlist_url, proxy=proxy, playlist_end=inventory_limit)
        cutoff_epoch = self.iso_utc_to_epoch(backfill_cutoff_iso) if backfill_cutoff_iso else 0

        hydrated: List[Dict[str, Any]] = []
        hydrated_ts: List[int] = []
        errors = 0
        oldest_ts: Optional[int] = None

        for item in inventory:
            if len(hydrated) >= hydrate_cap:
                break
            url = item.get("webpage_url") or item.get("url")
            if not url:
                continue

            try:
                v = self.hydrate_video_info(
                    url,
                    proxy=proxy,
                    download_archive=download_archive,
                    retries=retries,
                )
                ts = int(v.get("timestamp") or 0)

                # Only take items older than cutoff
                if cutoff_epoch and ts and ts >= cutoff_epoch:
                    continue

                v = self.enrich_video_with_transcripts(v, proxy=proxy, store_all_languages=store_all_languages)
                hydrated.append(v)
                hydrated_ts.append(ts)

                if ts:
                    if oldest_ts is None or ts < oldest_ts:
                        oldest_ts = ts
            except Exception:
                errors += 1

        hydrated_sorted = sorted(hydrated, key=lambda e: e.get("timestamp") or 0, reverse=True)

        run_metrics = self.assess_pagination(
            requested_inventory=inventory_limit,
            inventory_entries=inventory,
            hydrated_success=len(hydrated),
            hydrated_errors=errors,
            hydrated_timestamps=hydrated_ts,
        )
        run_metrics.update(
            {
                "at": self._now_utc_iso(),
                "mode": "backfill",
                "backfill_cutoff_iso": backfill_cutoff_iso,
                "inventory_limit": inventory_limit,
                "hydrate_cap": hydrate_cap,
            }
        )

        new_cutoff_iso = self.epoch_to_iso_utc(max(0, oldest_ts - 1)) if oldest_ts else None
        return hydrated_sorted, run_metrics, new_cutoff_iso

    # -----------------------------
    # ES integration convenience:
    # - update known timestamp & cutoff in state from run results
    # -----------------------------
    def update_state_from_newest_run(
        self,
        state: Dict[str, Any],
        videos: List[Dict[str, Any]],
        run_metrics: Dict[str, Any],
    ) -> Dict[str, Any]:
        # Only advance known timestamp on "ok" runs (conservative)
        flags = set(run_metrics.get("flags") or [])
        if "ok" not in flags:
            state["last_run"] = run_metrics
            return state

        # known timestamp = max epoch from this batch
        max_ts = 0
        for v in videos:
            ts = int(v.get("timestamp") or 0)
            if ts > max_ts:
                max_ts = ts

        if max_ts > 0:
            known_iso = state.get("known_timestamp_iso")
            known_epoch = self.iso_utc_to_epoch(known_iso) if known_iso else 0
            if max_ts > known_epoch:
                state["known_timestamp_iso"] = self.epoch_to_iso_utc(max_ts)
                # Initialize backfill cutoff on first successful known timestamp
                if not state.get("backfill_cutoff_iso"):
                    state["backfill_cutoff_iso"] = state["known_timestamp_iso"]

        state["last_run"] = run_metrics
        return state

    def update_state_from_backfill_run(
        self,
        state: Dict[str, Any],
        run_metrics: Dict[str, Any],
        new_cutoff_iso: Optional[str],
    ) -> Dict[str, Any]:
        if new_cutoff_iso:
            state["backfill_cutoff_iso"] = new_cutoff_iso
        state["last_run"] = run_metrics
        return state

    # -----------------------------
    # Convenience "controller" methods using ES state
    # -----------------------------
    def crawl_newest_with_es_state(
        self,
        *,
        es: Elasticsearch,
        profile: str,
        playlist_url: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 200,
        hydrate_cap: int = 30,
        store_all_languages: bool = False,
        state_index: str = DEFAULT_STATE_INDEX,
        asset_index: str = DEFAULT_ASSET_INDEX,
        download_archive: str = "tiktok_seen.txt",
        save_assets: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Loads state from ES, crawls newest, updates state, saves state back.
        NEW: Saves newly discovered TikTokAssets into `asset_index`.

        Returns: (videos, run_metrics, updated_state)
        """
        self.ensure_state_index(es, state_index=state_index)
        
        state = self.load_state(es, platform="tiktok", profile=profile, profile_url=playlist_url, state_index=state_index)

        videos, run = self.crawl_newest(playlist_url=playlist_url,
                                        proxy=proxy,
                                        inventory_limit=inventory_limit,
                                        hydrate_cap=hydrate_cap,
                                        known_timestamp_iso=state.get("known_timestamp_iso"),
                                        store_all_languages=store_all_languages,
                                        download_archive=download_archive,)

        # Save NEW assets first (before advancing known_timestamp)
        if save_assets:
            save_result = self.save_new_assets(es=es, videos=videos, asset_index=asset_index, refresh=False)
            run["asset_save"] = save_result

        state = self.update_state_from_newest_run(state, videos, run)
        self.save_state(es, state, state_index=state_index)
        return videos, run, state

    def backfill_with_es_state(
        self,
        *,
        es: Elasticsearch,
        profile: str,
        playlist_url: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 400,
        hydrate_cap: int = 50,
        store_all_languages: bool = False,
        state_index: str = DEFAULT_STATE_INDEX,
        asset_index: str = DEFAULT_ASSET_INDEX,
        download_archive: str = "tiktok_seen.txt",
        save_assets: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Loads state from ES, performs a backfill batch, updates cutoff, saves state back.
        NEW: Saves newly discovered TikTokAssets into `asset_index`.

        Returns: (videos, run_metrics, updated_state)
        """
        self.ensure_state_index(es, state_index=state_index)
        state = self.load_state(es, platform="tiktok", profile=profile, profile_url=playlist_url, state_index=state_index)

        cutoff = state.get("backfill_cutoff_iso") or state.get("known_timestamp_iso")
        videos, run, new_cutoff_iso = self.backfill_history(
            playlist_url=playlist_url,
            proxy=proxy,
            inventory_limit=inventory_limit,
            hydrate_cap=hydrate_cap,
            backfill_cutoff_iso=cutoff,
            store_all_languages=store_all_languages,
            download_archive=download_archive,
        )

        if save_assets:
            save_result = self.save_new_assets(es=es, videos=videos, asset_index=asset_index, refresh=False)
            run["asset_save"] = save_result

        state = self.update_state_from_backfill_run(state, run, new_cutoff_iso)
        self.save_state(es, state, state_index=state_index)
        return videos, run, state

    def upsert_asset(
        self,
        *,
        es: Elasticsearch,
        asset: Dict[str, Any],
        asset_index: str = DEFAULT_ASSET_INDEX,
    ) -> str:
        doc = self.build_tiktok_asset_doc(asset)
        if not doc:
            raise ValueError("Cannot upsert asset: build_tiktok_asset_doc returned empty doc")

        doc_id = doc["asset_id"]
        es.update(
            index=asset_index,
            id=doc["asset_id"], # makes the system-assigned `asset_id` the `_id` value in the document
            doc=doc,
            doc_as_upsert=True,
            refresh=False,
        )
        return doc_id
