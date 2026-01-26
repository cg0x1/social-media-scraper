from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple, Protocol

import requests
from elasticsearch7 import Elasticsearch, helpers
from yt_dlp import YoutubeDL
from AssetTranscriptLine import AssetTranscriptLine

# ============================================================
# Shared utilities + contracts
# ============================================================

def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def epoch_to_iso_utc(ts_seconds: int) -> str:
    return datetime.fromtimestamp(int(ts_seconds), tz=timezone.utc).isoformat().replace("+00:00", "Z")


def iso_utc_to_epoch(iso_str: str) -> int:
    dt = datetime.fromisoformat(iso_str.replace("Z", "+00:00"))
    return int(dt.timestamp())


class ScrapeError(RuntimeError):
    pass


class ParseError(RuntimeError):
    pass


class StorageError(RuntimeError):
    pass


class LoggerMixin:
    """Convenience mixin so every class has a logger with consistent naming."""
    @property
    def log(self) -> logging.Logger:
        return logging.getLogger(self.__class__.__name__)


# ========================================================================================================
# 1) Web Scraping / Fetching Concern
# 2) These definitions linked to any class with a method that matches the same definition in the Protocol
# ========================================================================================================

# class InventoryScraper(Protocol):
#     """
#     Inventory pass: cheap listing of entries without per-video hydration.
#     """
#     def inventory(self, playlist_url: str, *, proxy: Optional[str], limit: int) -> List[Dict[str, Any]]:
#         ...


# class VideoHydrator(Protocol):
#     """
#     Hydration pass: fetch full metadata for a single video.
#     """
#     def hydrate(self, video_url: str, *, proxy: Optional[str], download_archive: Optional[str], retries: int) -> Dict[str, Any]:
#         ...


# class CaptionFetcher(Protocol):
#     """
#     Fetch caption text from a URL.
#     """
#     def fetch_text(self, url: str, *, headers: Optional[dict], proxy: Optional[str], timeout: int = 30) -> str:
#         ...


class TikTokScraper(LoggerMixin):
    """
    Web scraping implementation using yt-dlp:
      - inventory(): extract_flat=True
      - hydrate():   extract_flat=False
    """

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def _ydl_inventory_options(proxy: Optional[str], playlist_end: int, quiet: bool = True) -> Dict[str, Any]:
        return {
            "skip_download": True,
            "proxy": proxy,
            "quiet": quiet,
            "verbose": True,
            "extract_flat": True,  # ✅ cheap inventory
            "nocheckcertificate": True,
            "playlistend": playlist_end,
            "writesubtitles": True,
            "writeautomaticsubtitles": True,
            "writeinfojson": False,
            "sleep_interval": 3,
            "max_sleep_interval": 5,
            "sleep_interval_requests": 1,
            "retries": 2,
        }

    @staticmethod
    def _ydl_hydrate_options(
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
        opts: Dict[str, Any] = {
            "skip_download": True,
            "proxy": proxy,
            "quiet": False,
            "verbose": verbose,
            "extract_flat": False,  # ✅ full hydration
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

    def inventory(self, playlist_url: str, *, proxy: Optional[str], limit: int) -> List[Dict[str, Any]]:
        try:
            with YoutubeDL(self._ydl_inventory_options(proxy, playlist_end=limit, quiet=True)) as ydl:
                info = ydl.extract_info(playlist_url, download=False)
        except Exception as ex:
            raise ScrapeError(f"Failed inventory for {playlist_url}: {ex}") from ex

        entries = [e for e in (info.get("entries") or []) if e]
        normed: List[Dict[str, Any]] = []
        for e in entries:
            url = e.get("url") or e.get("webpage_url") or e.get("id")
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

    def hydrate(self, video_url: str, *, proxy: Optional[str], download_archive: Optional[str], retries: int) -> Dict[str, Any]:
        try:
            with YoutubeDL(self._ydl_hydrate_options(proxy, retries=retries, download_archive=download_archive)) as ydl:
                return ydl.extract_info(video_url, download=False)
        except Exception as ex:
            raise ScrapeError(f"Failed hydrate for {video_url}: {ex}") from ex


class RequestsCaptionFetcher(LoggerMixin):
    """Raw text fetcher using requests. (You can swap for curl_cffi later if needed.)"""

    def fetch_text(self, url: str, *, headers: Optional[dict], proxy: Optional[str], timeout: int = 30) -> str:
        proxies = {"http": proxy, "https": proxy} if proxy else None
        try:
            r = requests.get(url, headers=headers or {}, proxies=proxies, timeout=timeout, verify=False)
            r.raise_for_status()
            return r.text
        except Exception as ex:
            raise ScrapeError(f"Failed caption fetch {url}: {ex}") from ex


class TranscriptParser(LoggerMixin):
    """Transforms VTT/SRT text into transcript_text + structured transcript_lines."""

    TICKS_PER_MS = 10_000
    TIMECODE_RE = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
    )

    def vtt_or_srt_to_text(self, s: str) -> str:
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
            if "-->" in line:
                continue
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line:
                lines.append(line)

        return re.sub(r"\s+", " ", " ".join(lines)).strip()

    def _time_to_ms(self, t: str) -> int:
        parts = t.split(":")
        if len(parts) == 3:
            h, m, rest = parts
        else:
            h = "0"
            m, rest = parts
        s, ms = rest.split(".")
        return int(h) * 3600_000 + int(m) * 60_000 + int(s) * 1000 + int(ms)

    def parse_to_lines(self, s: str) -> List[TranscriptLine]:
        if not s:
            return []

        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

        out: List[TranscriptLine] = []
        current_text: List[str] = []
        start_ms: Optional[int] = None
        end_ms: Optional[int] = None

        def flush() -> None:
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
                out.append(AssetTranscriptLine(offset_ms=offset, duration_ms=dur, total_ticks=ticks, content=content))

            current_text = []
            start_ms = None
            end_ms = None

        for raw_line in s.split("\n"):
            line = raw_line.strip()

            if not line:
                flush()
                continue

            if re.fullmatch(r"\d+", line):
                continue

            m = self.TIMECODE_RE.search(line)
            if m:
                flush()
                start_ms = self._time_to_ms(m.group("start"))
                end_ms = self._time_to_ms(m.group("end"))
                continue

            if "-->" in line:
                continue

            current_text.append(line)

        flush()
        return out


class CaptionTrackSelector:
    """Pure selection logic: choose caption URL(s) per language."""

    def get_tracks_by_language(
        self,
        info: Dict[str, Any],
        *,
        prefer_requested: bool = True,
        exts: Optional[set[str]] = None,
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

    def pick_language(self, captions_by_lang: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
        preferred = ["eng-US", "eng", "en", "en-US"]
        for p in preferred:
            if p in captions_by_lang:
                return p
        return next(iter(captions_by_lang.keys()), None)


class TikTokAssetFactory(LoggerMixin):
    """
    Builds your ES asset document from hydrated yt-dlp output + transcript enrichment.
    This is object-creation ONLY (no ES, no web calls).
    """

    def __init__(self, *, hash_len: int = 32):
        self.hash_len = hash_len

    @staticmethod
    def _asset_id_from_video_id(video_id: str) -> str:
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

    def _hash(self, s: str) -> str:
        h = hashlib.sha256(s.encode("utf-8")).hexdigest()
        return h[: self.hash_len]

    def enrich_transcript_hashes_inplace(self, doc: Dict[str, Any]) -> None:
        """
        "Best of both worlds": keep full text searchable, but also store stable hashes for dedupe/join.
        - transcript_hashes: [hash(line1), hash(line2), ...]
        - transcript_lines[*].content_hash
        """
        lines = doc.get("transcript_lines") or []
        if not isinstance(lines, list):
            return

        hashes: List[str] = []
        for l in lines:
            if not isinstance(l, dict):
                continue
            content = (l.get("content") or "").strip()
            if not content:
                continue
            ch = self._hash(content)
            l["content_hash"] = ch
            hashes.append(ch)

        if hashes:
            doc["transcript_hashes"] = hashes

    def build_asset_doc(self, hydrated: Dict[str, Any]) -> Dict[str, Any]:
        video_id = str(hydrated.get("id") or "").strip()
        if not video_id:
            return {}

        ts_epoch = hydrated.get("timestamp")
        ts_iso = None
        if isinstance(ts_epoch, (int, float)) and ts_epoch:
            ts_iso = epoch_to_iso_utc(int(ts_epoch))
        elif isinstance(ts_epoch, str) and ts_epoch:
            ts_iso = ts_epoch

        subtitles_blob = hydrated.get("requested_subtitles") or hydrated.get("subtitles") or hydrated.get("automatic_captions")

        doc: Dict[str, Any] = {
            "asset_id": self._asset_id_from_video_id(video_id),
            "id": video_id,
            "display_id": hydrated.get("display_id"),
            "channel": hydrated.get("channel"),
            "channel_id": hydrated.get("channel_id"),
            "uploader": hydrated.get("uploader"),
            "uploader_id": str(hydrated.get("uploader_id")) if hydrated.get("uploader_id") is not None else None,
            "playlist": hydrated.get("playlist"),
            "playlist_id": hydrated.get("playlist_id"),
            "playlist_title": hydrated.get("playlist_title"),
            "title": hydrated.get("title"),
            "description": hydrated.get("description"),
            "artists": self._flatten_artists(hydrated),
            "view_count": hydrated.get("view_count"),
            "like_count": hydrated.get("like_count"),
            "comment_count": hydrated.get("comment_count"),
            "repost_count": hydrated.get("repost_count"),
            "upload_date": hydrated.get("upload_date"),
            "duration": hydrated.get("duration"),
            "timestamp": ts_iso,
            "track": hydrated.get("track"),
            "webpage_url": hydrated.get("webpage_url"),
            "original_url": hydrated.get("original_url"),
            "channel_url": hydrated.get("channel_url"),
            "uploader_url": hydrated.get("uploader_url"),
            "playlist_webpage_url": hydrated.get("playlist_webpage_url"),
            "thumbnail": self._pick_thumbnail(hydrated),
            "subtitles": subtitles_blob,
            "transcript_lang": hydrated.get("transcript_lang"),
            "transcript_text": hydrated.get("transcript_text"),
            "transcript_lines": hydrated.get("transcript_lines"),
        }

        # remove Nones
        doc = {k: v for k, v in doc.items() if v is not None}

        # add hashes for dedupe / correlation
        self.enrich_transcript_hashes_inplace(doc)
        return doc


# ================================
# 3) execution history persistence
# ================================
class CrawlStateRepository(LoggerMixin):
    """CRUD for crawl tracing history/state."""
    DEFAULT_STATE_INDEX = "tiktok-crawl-state"

    def __init__(self, es: Elasticsearch, *, index: str = DEFAULT_STATE_INDEX):
        self.es = es
        self.index = index

    @staticmethod
    def state_doc_id(platform: str, profile: str) -> str:
        return f"{platform}:{profile}"

    def ensure_index(self) -> None:
        if self.es.indices.exists(index=self.index):
            return
        self.es.indices.create(
            index=self.index,
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

    def load(self, *, platform: str, profile: str, profile_url: str) -> Dict[str, Any]:
        doc_id = self.state_doc_id(platform, profile)
        try:
            resp = self.es.get(index=self.index, id=doc_id)
            src = resp.get("_source") or {}
        except Exception:
            src = {}

        src.setdefault("platform", platform)
        src.setdefault("profile", profile)
        src.setdefault("profile_url", profile_url)
        src.setdefault("known_timestamp_iso", None)
        src.setdefault("backfill_cutoff_iso", None)
        src.setdefault("last_run", None)
        return src

    def save(self, state: Dict[str, Any]) -> None:
        doc_id = self.state_doc_id(state.get("platform", "tiktok"), state.get("profile", ""))
        try:
            self.es.index(index=self.index, id=doc_id, document=state, refresh=False)
        except Exception as ex:
            raise StorageError(f"Failed saving state: {ex}") from ex


# ================================
# 3) Asset persistence
# ================================
class TikTokAssetRepository(LoggerMixin):
    """CRUD for video storage in the `tiktok-assets` index."""
    DEFAULT_ASSET_INDEX = "tiktok-assets"

    def __init__(self, es: Elasticsearch, *, index: str = DEFAULT_ASSET_INDEX):
        self.es = es
        self.index = index

    def ensure_index_exists(self) -> None:
        if not self.es.indices.exists(index=self.index):
            raise StorageError(f"Missing index '{self.index}'. Create it using your mapping.")

    def create_only_bulk(self, docs: Iterable[Dict[str, Any]], *, refresh: bool = False) -> Dict[str, int]:
        actions = []
        for d in docs:
            doc_id = d.get("asset_id")
            if not doc_id:
                continue
            actions.append({"_op_type": "create", "_index": self.index, "_id": doc_id, "_source": d})

        if not actions:
            return {"attempted": 0, "created": 0, "conflicts": 0, "errors": 0}

        created = conflicts = errors = attempted = 0
        for ok, item in helpers.streaming_bulk(
            self.es,
            actions,
            raise_on_error=False,
            raise_on_exception=False,
            yield_ok=True,
        ):
            attempted += 1
            op = item.get("create") or {}
            status = op.get("status")
            if ok and status in (200, 201):
                created += 1
            elif status == 409:
                conflicts += 1
            else:
                errors += 1

        if refresh:
            self.es.indices.refresh(index=self.index)

        return {"attempted": attempted, "created": created, "conflicts": conflicts, "errors": errors}

    def upsert(self, doc: Dict[str, Any]) -> str:
        doc_id = doc.get("asset_id")
        if not doc_id:
            raise StorageError("Cannot upsert without asset_id")
        try:
            self.es.update(index=self.index, id=doc_id, doc=doc, doc_as_upsert=True, refresh=False)
            return doc_id
        except Exception as ex:
            raise StorageError(f"Failed upsert {doc_id}: {ex}") from ex


# ============================================================
# 4) Orchestration (thin service that composes concerns)
# ============================================================

class TikTokCrawlService(LoggerMixin):
    """
    Orchestrates:
      - web scrape inventory/hydrate
      - captions fetch + parse
      - asset creation
      - ES state + asset persistence

    This keeps each component single-purpose, and this class stays *thin*.
    """

    def __init__(
        self,
        *,
        scraper: TikTokScraper,
        caption_fetcher: RequestsCaptionFetcher,
        caption_selector: CaptionTrackSelector,
        transcript_parser: TranscriptParser,
        asset_factory: TikTokAssetFactory,
        state_repo: CrawlStateRepository,
        asset_repo: TikTokAssetRepository,
    ):
        self.scraper = scraper
        self.caption_fetcher = caption_fetcher
        self.caption_selector = caption_selector
        self.transcript_parser = transcript_parser
        self.asset_factory = asset_factory
        self.state_repo = state_repo
        self.asset_repo = asset_repo

    def _enrich_with_transcripts(
        self,
        hydrated: Dict[str, Any],
        *,
        proxy: Optional[str],
        store_all_languages: bool,
    ) -> Dict[str, Any]:
        hydrated["transcript_text"] = ""
        hydrated["transcript_lang"] = None
        hydrated["transcript_lines"] = []
        hydrated["transcript_lines_by_lang"] = {} if store_all_languages else None
        hydrated["transcripts"] = {} if store_all_languages else None

        captions = self.caption_selector.get_tracks_by_language(
            hydrated,
            prefer_requested=False,
            exts={"vtt", "srt"},
        )
        if not captions:
            return hydrated

        headers = hydrated.get("http_headers") or {}

        if store_all_languages:
            for lang, tracks in captions.items():
                if not tracks:
                    continue
                track = tracks[0]
                try:
                    raw = self.caption_fetcher.fetch_text(track["url"], headers=headers, proxy=proxy)
                    hydrated["transcripts"][lang] = self.transcript_parser.vtt_or_srt_to_text(raw)
                    hydrated["transcript_lines_by_lang"][lang] = [l.to_doc() for l in self.transcript_parser.parse_to_lines(raw)]
                except Exception as ex:
                    hydrated["transcripts"][lang] = f"__error__: {ex}"
                    hydrated["transcript_lines_by_lang"][lang] = []

            chosen = self.caption_selector.pick_language({k: v for k, v in captions.items() if v})
            if chosen:
                hydrated["transcript_lang"] = chosen
                hydrated["transcript_text"] = hydrated["transcripts"].get(chosen, "") or ""
                hydrated["transcript_lines"] = hydrated["transcript_lines_by_lang"].get(chosen, []) or []
        else:
            chosen = self.caption_selector.pick_language(captions)
            if not chosen:
                return hydrated
            track = captions[chosen][0]
            try:
                raw = self.caption_fetcher.fetch_text(track["url"], headers=headers, proxy=proxy)
                hydrated["transcript_lang"] = chosen
                hydrated["transcript_text"] = self.transcript_parser.vtt_or_srt_to_text(raw)
                hydrated["transcript_lines"] = [l.to_doc() for l in self.transcript_parser.parse_to_lines(raw)]
            except Exception as ex:
                hydrated["transcript_lang"] = chosen
                hydrated["transcript_text"] = f"__error__: {ex}"
                hydrated["transcript_lines"] = []

        return hydrated

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

        disorder = 0
        ts = [t for t in hydrated_timestamps if t]
        if len(ts) >= 2:
            disorder = sum(1 for a, b in zip(ts, ts[1:]) if b > a)

        flags: List[str] = []
        if inv_count < int(requested_inventory * 0.8):
            flags.append(f"short_inventory:{inv_count}/{requested_inventory}")
        if dup_rate > 0.05:
            flags.append(f"dup_rate:{dup_rate:.1%}")

        attempted = hydrated_success + hydrated_errors
        if attempted:
            err_rate = hydrated_errors / attempted
            if err_rate > 0.2:
                flags.append(f"high_error_rate:{err_rate:.1%}")

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

    def crawl_newest_with_es_state(
        self,
        *,
        profile: str,
        playlist_url: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 200,
        hydrate_cap: int = 30,
        store_all_languages: bool = False,
        download_archive: str = "tiktok_seen.txt",
        save_assets: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        # Ensure persistence is ready
        self.state_repo.ensure_index()
        if save_assets:
            self.asset_repo.ensure_index_exists()

        state = self.state_repo.load(platform="tiktok", profile=profile, profile_url=playlist_url)
        known_iso = state.get("known_timestamp_iso")
        stop_epoch = iso_utc_to_epoch(known_iso) if known_iso else 0

        inventory = self.scraper.inventory(playlist_url, proxy=proxy, limit=inventory_limit)

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
                v = self.scraper.hydrate(url, proxy=proxy, download_archive=download_archive, retries=2)
                ts = int(v.get("timestamp") or 0)

                v = self._enrich_with_transcripts(v, proxy=proxy, store_all_languages=store_all_languages)

                hydrated.append(v)
                hydrated_ts.append(ts)

                if stop_epoch and ts and ts <= stop_epoch:
                    break
            except Exception:
                errors += 1

        hydrated_sorted = sorted(hydrated, key=lambda e: e.get("timestamp") or 0, reverse=True)

        run = self.assess_pagination(
            requested_inventory=inventory_limit,
            inventory_entries=inventory,
            hydrated_success=len(hydrated),
            hydrated_errors=errors,
            hydrated_timestamps=hydrated_ts,
        )
        run.update(
            {
                "at": utc_now_iso(),
                "mode": "newest",
                "known_timestamp_iso": known_iso,
                "inventory_limit": inventory_limit,
                "hydrate_cap": hydrate_cap,
            }
        )

        # Persist assets (create-only bulk)
        if save_assets:
            docs = [self.asset_factory.build_asset_doc(v) for v in hydrated_sorted]
            docs = [d for d in docs if d]
            save_result = self.asset_repo.create_only_bulk(docs, refresh=False)
            run["asset_save"] = save_result

        # Update state conservatively
        flags = set(run.get("flags") or [])
        if "ok" in flags:
            max_ts = max((int(v.get("timestamp") or 0) for v in hydrated_sorted), default=0)
            if max_ts:
                prior = iso_utc_to_epoch(state["known_timestamp_iso"]) if state.get("known_timestamp_iso") else 0
                if max_ts > prior:
                    state["known_timestamp_iso"] = epoch_to_iso_utc(max_ts)
                    if not state.get("backfill_cutoff_iso"):
                        state["backfill_cutoff_iso"] = state["known_timestamp_iso"]

        state["last_run"] = run
        self.state_repo.save(state)

        return hydrated_sorted, run, state


# # ============================================================
# # Example wiring (how you’d use this)
# # ============================================================

# def build_tiktok_crawl_service(es: Elasticsearch, *, state_index: str, asset_index: str, hash_len: int = 32) -> TikTokCrawlService:
#     return TikTokCrawlService(
#         scraper=TikTokScraper(),
#         caption_fetcher=RequestsCaptionFetcher(),
#         caption_selector=CaptionTrackSelector(),
#         transcript_parser=TranscriptParser(),
#         asset_factory=TikTokAssetFactory(hash_len=hash_len),
#         state_repo=CrawlStateRepository(es, index=state_index),
#         asset_repo=TikTokAssetRepository(es, index=asset_index),
#     )


# Usage:
# service = build_tiktok_crawl_service(es, state_index="tiktok-crawl-state", asset_index="tiktok-assets", hash_len=32)
# videos, run, state = service.crawl_newest_with_es_state(
#     profile="@chasingoz",
#     playlist_url="https://www.tiktok.com/@chasingoz",
#     proxy=PROXY_URL,
#     inventory_limit=50,
#     hydrate_cap=10,
#     store_all_languages=False,
#     download_archive="tiktok_seen.txt",
#     save_assets=True,
# )
