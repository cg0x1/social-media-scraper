from __future__ import annotations

import hashlib
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests
from elasticsearch7 import Elasticsearch, helpers
from yt_dlp import YoutubeDL

from TikTokAsset import TikTokAsset
from TikTokAssetTranscript import TikTokAssetTranscript, TikTokTranscriptLine
from RateLimiter import RateLimiter

import random
import time
from typing import Callable, Tuple, TypeVar

T = TypeVar("T")

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


# ============================================================
# 1) Web Scraping / Fetching Concern
# ============================================================

class TikTokScraper(LoggerMixin):
    """
    Web scraping implementation using yt-dlp:
      - inventory(): extract_flat=True
      - hydrate():   extract_flat=False
    """

    def __init__(self) -> None:
        super().__init__()

    @staticmethod
    def ydl_playlist_options(
        *,
        proxy: Optional[str],
        playlist_end: int,
        quiet: bool = True,
        download_archive: Optional[str] = None,
        verbose: bool = True,
        retries: int = 2,
        sleep_interval: int = 2,
        max_sleep_interval: int = 5,
        sleep_interval_requests: int = 1,
    ) -> Dict[str, Any]:
        """
        Inventory pass: list the newest N entries for a profile/playlist URL.

        Notes:
        - extract_flat=True is cheap inventory (NOT "full metadata").
        - Disable subtitle probing here to avoid extra network calls; do subtitles on hydration.
        """
        opts: Dict[str, Any] = {
            "skip_download": True,
            "proxy": proxy,
            "quiet": quiet,
            "verbose": verbose,
            "extract_flat": True,      # ✅ inventory / cheap listing
            "nocheckcertificate": True,
            "playliststart": 1,
            "playlistend": int(playlist_end),
            "writesubtitles": False,            # ✅ avoid extra requests during inventory
            "writeautomaticsubtitles": False,   # ✅ avoid extra requests during inventory
            "writeinfojson": False,
            "sleep_interval": sleep_interval,
            "max_sleep_interval": max_sleep_interval,
            "sleep_interval_requests": sleep_interval_requests,
            "retries": retries,
        }
        if download_archive:
            opts["download_archive"] = download_archive
        return opts

    @staticmethod
    def ydl_hydrate_options(
        *,
        proxy: Optional[str],
        quiet: bool = False,
        download_archive: Optional[str] = None,
        verbose: bool = True,
        retries: int = 2,
        sleep_interval: int = 2,
        max_sleep_interval: int = 5,
        sleep_interval_requests: int = 1,
        include_subtitles: bool = True,
    ) -> Dict[str, Any]:
        """
        Hydration pass: fetch full metadata for a single video URL.

        Notes:
        - extract_flat=False gives full info dict.
        - noplaylist=True prevents accidental playlist expansion during hydration.
        """
        opts: Dict[str, Any] = {
            "skip_download": True,
            "proxy": proxy,
            "quiet": quiet,
            "verbose": verbose,
            "extract_flat": False,     # ✅ full hydration
            "nocheckcertificate": True,
            "noplaylist": True,        # ✅ critical for single-video hydration
            "writesubtitles": bool(include_subtitles),
            "writeautomaticsubtitles": bool(include_subtitles),
            "writeinfojson": False,
            "sleep_interval": sleep_interval,
            "max_sleep_interval": max_sleep_interval,
            "sleep_interval_requests": sleep_interval_requests,
            "retries": retries,
        }
        if download_archive:
            opts["download_archive"] = download_archive
        return opts

    def inventory(self, playlist_url: str, *, proxy: str, limit: int, inventory_archive: str) -> List[Dict[str, Any]]:
        try:
            if not proxy or len(proxy) == 0:                
                raise ValueError(f"A proxy must be provided!")
            
            options = options = TikTokScraper.ydl_playlist_options(proxy=proxy,
                                                                   playlist_end=limit,
                                                                   quiet=True,
                                                                   verbose=False,
                                                                   retries=1,
                                                                   download_archive=inventory_archive
                                                                  )
            with YoutubeDL(options) as ydl:
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

    def hydrate(self, video_url: str, *, proxy: str) -> Dict[str, Any]:
        try:
            options = TikTokScraper.ydl_hydrate_options(proxy=proxy,
                                                        quiet=False,
                                                        download_archive="tiktok_seen.txt",
                                                        verbose=True,
                                                        retries=2,
                                                        sleep_interval=2,
                                                        max_sleep_interval= 5,
                                                        sleep_interval_requests= 1,
                                                        include_subtitles=True,)
            with YoutubeDL(options) as ydl:
                return ydl.extract_info(video_url, download=False)
        except Exception as ex:
            raise ScrapeError(f"Failed hydrate for {video_url}: {ex}") from ex


class RequestsCaptionFetcher(LoggerMixin):
    """Raw text fetcher using requests."""

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

    def parse_to_lines(self, s: str) -> List[TikTokTranscriptLine]:
        """
        Returns AssetTranscriptLine objects (int ms fields).
        TikTokAssetFactory converts these to TikTokTranscriptLine (float fields) for ES transcript index.
        """
        if not s:
            return []

        s = s.replace("\r\n", "\n").replace("\r", "\n")
        s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

        out: List[TikTokTranscriptLine] = []
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
                out.append(TikTokTranscriptLine(offset_ms=offset, duration_ms=dur, total_ticks=ticks, content=content))

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


# ============================================================
# Object creation ONLY (no ES, no web calls)
# ============================================================

class TikTokAssetFactory(LoggerMixin):
    """
    Builds TikTokAsset + TikTokAssetTranscript from hydrated yt-dlp output + parsed transcripts.
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

    def compute_transcript_hashes_and_line_hashes(
        self,
        lines: List[TikTokTranscriptLine],  # ✅ FIX: accept AssetTranscriptLine (what parser returns)
    ) -> Tuple[List[str], List[TikTokTranscriptLine]]:
        """
        Produces:
          - transcript_hashes: list[str]
          - transcript_lines: list[TikTokTranscriptLine] (float offset/duration per mapping)
        """
        hashes: List[str] = []
        out_lines: List[TikTokTranscriptLine] = []

        for l in lines:
            content = (l.content or "").strip()
            if not content:
                continue
            ch = self._hash(content)
            hashes.append(ch)

            out_lines.append(
                TikTokTranscriptLine(
                    offset_ms=float(l.offset_ms),
                    duration_ms=float(l.duration_ms),
                    total_ticks=int(l.total_ticks) if l.total_ticks is not None else None,
                    content=content,
                    content_hash=ch,
                )
            )

        return hashes, out_lines

    def build_asset_and_transcript(
        self,
        hydrated: Dict[str, Any],
        *,
        source_id: str,
        transcript_lang: Optional[str],
        transcript_text: str,
        transcript_lines: List[TikTokTranscriptLine],
        subtitles_lang_url_map: Optional[Dict[str, str]],
    ) -> Tuple[Optional[TikTokAsset], Optional[TikTokAssetTranscript]]:
        video_id = str(hydrated.get("id") or "").strip()
        if not video_id:
            return None, None

        ts_epoch = hydrated.get("timestamp")
        ts_iso: Optional[str] = None
        if isinstance(ts_epoch, (int, float)) and ts_epoch:
            ts_iso = epoch_to_iso_utc(int(ts_epoch))
        elif isinstance(ts_epoch, str) and ts_epoch:
            ts_iso = ts_epoch

        asset_id = self._asset_id_from_video_id(video_id)

        transcript_hashes, transcript_lines_es = self.compute_transcript_hashes_and_line_hashes(transcript_lines)

        asset = TikTokAsset(
            asset_id=asset_id,
            id=video_id,
            display_id=hydrated.get("display_id"),
            channel=hydrated.get("channel"),
            channel_id=hydrated.get("channel_id"),
            uploader=hydrated.get("uploader"),
            uploader_id=str(hydrated.get("uploader_id")) if hydrated.get("uploader_id") is not None else None,
            playlist=hydrated.get("playlist"),
            playlist_id=hydrated.get("playlist_id"),
            playlist_title=hydrated.get("playlist_title"),
            title=hydrated.get("title"),
            description=hydrated.get("description"),
            artists=self._flatten_artists(hydrated),
            view_count=hydrated.get("view_count"),
            like_count=hydrated.get("like_count"),
            comment_count=hydrated.get("comment_count"),
            repost_count=hydrated.get("repost_count"),
            upload_date=hydrated.get("upload_date"),
            duration=hydrated.get("duration"),
            timestamp=ts_iso,
            track=hydrated.get("track"),
            webpage_url=hydrated.get("webpage_url"),
            original_url=hydrated.get("original_url"),
            channel_url=hydrated.get("channel_url"),
            uploader_url=hydrated.get("uploader_url"),
            playlist_webpage_url=hydrated.get("playlist_webpage_url"),
            thumbnail=self._pick_thumbnail(hydrated),
            subtitles=subtitles_lang_url_map,  # dict(lang->url), stored enabled:false
            transcript_lang=transcript_lang,
            transcript_hashes=transcript_hashes if transcript_hashes else None,
        )

        transcript = TikTokAssetTranscript(
            asset_id=asset_id,
            source_id=source_id,
            transcript_lang=transcript_lang,
            transcript_text=transcript_text,
            transcript_hashes=transcript_hashes if transcript_hashes else None,
            transcript_lines=transcript_lines_es,
            created_at=None,
            updated_at=None,
        )

        return asset, transcript


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


class TikTokAssetTranscriptRepository(LoggerMixin):
    """CRUD for transcript storage in the `tiktok-asset-transcripts` index."""
    DEFAULT_INDEX = "tiktok-asset-transcripts"

    def __init__(self, es: Elasticsearch, *, index: str = DEFAULT_INDEX):
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


# ============================================================
# 4) Orchestration
# ============================================================

class TikTokCrawlService(LoggerMixin):
    """
    Orchestrates:
      - web scraping inventory/hydrate
      - captions fetch + parse
      - asset + transcript object creation
      - ES state + asset/transcript persistence
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
        transcript_repo: TikTokAssetTranscriptRepository,
        discovery_interval_wait_seconds: float = 2.5,
    ):
        """
        Initializes a new TikTokCrawlService instance
        
        :param self: Description
        :param scraper: Description
        :type scraper: TikTokScraper
        :param caption_fetcher: Description
        :type caption_fetcher: RequestsCaptionFetcher
        :param caption_selector: Description
        :type caption_selector: CaptionTrackSelector
        :param transcript_parser: Description
        :type transcript_parser: TranscriptParser
        :param asset_factory: Description
        :type asset_factory: TikTokAssetFactory
        :param state_repo: Description
        :type state_repo: CrawlStateRepository
        :param asset_repo: Description
        :type asset_repo: TikTokAssetRepository
        :param transcript_repo: Description
        :type transcript_repo: TikTokAssetTranscriptRepository
        :param discovery_interval_wait_seconds: Description
        :type discovery_interval_wait_seconds: float
        """
        self.scraper = scraper
        self.caption_fetcher = caption_fetcher
        self.caption_selector = caption_selector
        self.transcript_parser = transcript_parser
        self.asset_factory = asset_factory
        self.state_repo = state_repo
        self.asset_repo = asset_repo
        self.transcript_repo = transcript_repo        
        self._rate_limiter = RateLimiter(min_interval_s=discovery_interval_wait_seconds)

    def with_backoff_tiktok(
        fn: Callable[[], T],
        *,
        max_attempts: int = 6,
        base_delay_s: float = 1.25,
        max_delay_s: float = 45.0,
        retry_on: Tuple[type, ...] = (Exception,),
        on_retry=None,
    ) -> T:
        """
        TikTok-tuned backoff:
        - bounded full jitter
        - slightly more attempts
        - larger max delay (TikTok often needs longer cool-down)
        """
        for attempt in range(1, max_attempts + 1):
            try:
                return fn()
            except retry_on as ex:
                if attempt >= max_attempts:
                    raise

                cap = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
                delay = random.uniform(0.0, cap)  # ✅ full jitter

                if on_retry:
                    on_retry(attempt, delay, ex)

                time.sleep(delay)

        raise RuntimeError("unreachable")

    def _with_backoff(self,
        fn,
        *,
        max_attempts: int = 5,
        base_delay_s: float = 1.0,
        max_delay_s: float = 30.0,
        jitter_s: float = 0.4,
        retry_on: Tuple[type, ...] = (Exception,),
        on_retry=None, ):
        """
        A helper function that wraps the `fn` parameter with a retry mechanism and delay
        
        :param self: Description
        :param fn: The function to invoke
        :param max_attempts: The maximum number of retry attemtps
        :type max_attempts: int
        :param base_delay_s: the minimum delay (in seconds) before invoking the wrapped function
        :type base_delay_s: float
        :param max_delay_s: the maximum delay (in seconds)
        :type max_delay_s: float
        :param jitter_s: a small, random delay added to a scheduled wait time
        :type jitter_s: float
        :param retry_on: Description
        :type retry_on: Tuple[type, ...]
        :param on_retry: Description
        """
        import random
        import time

        attempt = 0
        while True:
            attempt += 1
            try:
                return fn()
            except retry_on as ex:
                if attempt >= max_attempts:
                    raise
                delay = min(max_delay_s, base_delay_s * (2 ** (attempt - 1)))
                delay = delay + random.uniform(0, jitter_s)
                if on_retry:
                    on_retry(attempt, delay, ex)
                time.sleep(delay)
                
    def _subtitles_lang_url_map(self, hydrated: Dict[str, Any]) -> Optional[Dict[str, str]]:
        """
        Builds a simple dict(lang -> url) from yt-dlp subtitles/automatic/requested structures.
        Stored as enabled:false in `tiktok-assets`.
        """
        out: Dict[str, str] = {}
        for key in ("requested_subtitles", "subtitles", "automatic_captions"):
            blob = hydrated.get(key) or {}
            if not isinstance(blob, dict):
                continue
            for lang, tracks in blob.items():
                if not lang:
                    continue
                if isinstance(tracks, dict):
                    url = tracks.get("url")
                    if isinstance(url, str) and url.strip():
                        out[str(lang)] = url.strip()
                    continue
                if isinstance(tracks, list) and tracks:
                    for t in tracks:
                        if isinstance(t, dict):
                            url = t.get("url")
                            if isinstance(url, str) and url.strip():
                                out[str(lang)] = url.strip()
                                break
        return out or None

    def _fetch_and_parse_transcript(
        self,
        hydrated: Dict[str, Any],
        *,
        proxy: Optional[str],
    ) -> Tuple[str, str, List[TikTokTranscriptLine]]:
        """
        Retrieves and parses a transcript for a video
        
        :param self: Description
        :param hydrated: Description
        :type hydrated: Dict[str, Any]
        :param proxy: Description
        :type proxy: Optional[str]
        :return: Description
        :rtype: Tuple[str, str, List[TikTokTranscriptLine]]
        """        
        captions = self.caption_selector.get_tracks_by_language(hydrated, prefer_requested=False, exts={"vtt", "srt"},)
        if not captions:
            return None, None, None
            # present = [k for k in ("requested_subtitles", "subtitles", "automatic_captions") if hydrated.get(k)]
            # raise ScrapeError(f"No caption tracks found. Present caption keys={present}")

        chosen = self.caption_selector.pick_language(captions)
        if not chosen:
            raise ScrapeError(f"Could not select caption language. langs={list(captions.keys())}")

        track = captions[chosen][0]
        
        headers = hydrated.get("http_headers") or {}

        raw = self.caption_fetcher.fetch_text(track["url"], headers=headers, proxy=proxy)

        # Guard: sometimes an HTML error page shows instead of VTT/SRT
        head = raw.lstrip()[:200].lower()
        if "<html" in head:
            raise ScrapeError(f"Caption fetch returned HTML (blocked/expired). lang={chosen} url={track.get('url')}")

        text = self.transcript_parser.vtt_or_srt_to_text(raw)
        
        lines = self.transcript_parser.parse_to_lines(raw)

        if not text and not lines:
            raise ParseError(f"Caption fetched but parsed empty transcript. lang={chosen} url={track.get('url')}")

        return chosen, text, lines

    @staticmethod
    def assess_pagination(
        *,
        requested_inventory: int,
        inventory_entries: List[Dict[str, Any]],
        hydrated_success: int,
        hydrated_errors: int,
        hydrated_timestamps: List[int],
    ) -> Dict[str, Any]:
        """
        Used to identify if a crawl was given the correct number of newest items.
        
        :param requested_inventory: Description
        :type requested_inventory: int
        :param inventory_entries: Description
        :type inventory_entries: List[Dict[str, Any]]
        :param hydrated_success: Description
        :type hydrated_success: int
        :param hydrated_errors: Description
        :type hydrated_errors: int
        :param hydrated_timestamps: Description
        :type hydrated_timestamps: List[int]
        :return: Description
        :rtype: Dict[str, Any]
        """
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
        source_id: str,
        proxy: Optional[str] = None,
        inventory_limit: int = 10,
        hydrate_cap: int = 10,
        download_archive: str = "tiktok_seen.txt",
        save_assets: bool = True,
    ) -> Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]:
        """
        Crawls the specified profile using Elasticsearch for historical tracing persistence
        
        :param self: a reference
        :param profile: the TikTok profile
        :type profile: str
        :param playlist_url: Description
        :type playlist_url: str
        :param source_id: Description
        :type source_id: str
        :param proxy: Description
        :type proxy: Optional[str]
        :param inventory_limit: Description
        :type inventory_limit: int
        :param hydrate_cap: Description
        :type hydrate_cap: int
        :param download_archive: Description
        :type download_archive: str
        :param save_assets: Description
        :type save_assets: bool
        :return: Description
        :rtype: Tuple[List[Dict[str, Any]], Dict[str, Any], Dict[str, Any]]
        """        
        # Ensure persistence is ready
        self.state_repo.ensure_index()
        if save_assets:
            self.asset_repo.ensure_index_exists()
            self.transcript_repo.ensure_index_exists()

        state = self.state_repo.load(platform="tiktok", profile=profile, profile_url=playlist_url)
        known_iso = state.get("known_timestamp_iso")
        stop_epoch = iso_utc_to_epoch(known_iso) if known_iso else 0

        # `inventory_limit` is the max number of videos pulled from a playlist
        inventory = self.scraper.inventory(playlist_url, proxy=proxy, limit=inventory_limit, inventory_archive=download_archive)

        inventory = inventory[:inventory_limit] # hard cap

        hydrated: List[Dict[str, Any]] = []
        hydrated_ts: List[int] = []
        errors = 0

        asset_docs: List[Dict[str, Any]] = []
        transcript_docs: List[Dict[str, Any]] = []

        for item in inventory:
            if len(hydrated) >= hydrate_cap:
                break

            url = item.get("webpage_url") or item.get("url")
            if not url:
                continue

            try:
                #v = self.scraper.hydrate(url, proxy=proxy,)#, max_playlist=inventory_limit)
                
                def do_hydrate():
                    self._rate_limiter.wait()
                    return self.scraper.hydrate(url, proxy=proxy)

                v = self._with_backoff(do_hydrate,
                                        max_attempts=2,
                                        base_delay_s=1.5,
                                        max_delay_s=25.0,
                                        jitter_s=0.6,
                                        on_retry=lambda attempt, delay, ex: self.log.warning(
                                            "hydrate retry %d in %.1fs url=%s err=%s", attempt, delay, url, ex),)


                ts = int(v.get("timestamp") or 0)

                # transcript extraction
                lang, text, lines = self._fetch_and_parse_transcript(v, proxy=proxy)
                
                # only process videos with a transcript
                if lang and text and lines:

                    subtitles_map = self._subtitles_lang_url_map(v)

                    asset, transcript_obj = self.asset_factory.build_asset_and_transcript(
                        v,
                        source_id=source_id,
                        transcript_lang=lang,
                        transcript_text=text,
                        transcript_lines=lines,
                        subtitles_lang_url_map=subtitles_map,
                    )

                    if asset and transcript_obj:
                        asset_docs.append(asset.to_es_doc(include_subtitles=True))
                        transcript_docs.append(transcript_obj.to_es_doc())

                    hydrated.append(v)
                    hydrated_ts.append(ts)
                else:
                    self.log.info(f"Skipped The asset at {url}; no transcript")
                
                if stop_epoch and ts and ts <= stop_epoch:
                    break

            except Exception as ex:
                errors += 1
                self.log.exception("Failed processing url=%s item=%s: %s", url, item, ex)

        self.log.info("Prepared docs: assets=%d transcripts=%d errors=%d", len(asset_docs), len(transcript_docs), errors)

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

        if save_assets:
            run["asset_save"] = self.asset_repo.create_only_bulk(asset_docs, refresh=False)
            run["transcript_save"] = self.transcript_repo.create_only_bulk(transcript_docs, refresh=False)

            self.log.info("Bulk results: asset_save=%s transcript_save=%s", run.get("asset_save"), run.get("transcript_save"))

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
        
        self.state_repo.save(state) # save the trace history of this run

        return hydrated_sorted, run, state
