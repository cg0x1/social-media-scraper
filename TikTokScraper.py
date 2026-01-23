import re
from typing import Any, Dict, List, Optional, Tuple
import requests
from yt_dlp import YoutubeDL
from dataclasses import dataclass


@dataclass
class AssetTranscriptLine:
    offset_ms: float
    duration_ms: float
    total_ticks: int
    content: str


class TikTokScraper:

    TICKS_PER_MS = 10_000
    TIMECODE_RE = re.compile(
        r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+"
        r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})"
    )

    # -----------------------------
    # 1) caption URL extraction
    # -----------------------------
    def get_transcript_urls_by_language(
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

    # -----------------------------
    # 2) download + parse caption text
    # -----------------------------
    def _download_text(self, url: str, headers: Optional[dict], proxy: Optional[str], timeout: int = 30) -> str:
        proxies = None
        if proxy:
            proxies = {"http": proxy, "https": proxy}

        r = requests.get(url, headers=headers or {}, proxies=proxies, timeout=timeout)
        r.raise_for_status()
        return r.text

    def _vtt_or_srt_to_text(self, s: str) -> str:
        """
        Best-effort conversion of VTT/SRT to readable text:
        - strips WEBVTT header
        - strips timestamps and cue indices
        - strips simple <...> tags
        - collapses whitespace
        """
        if not s:
            return ""

        # Normalize newlines
        s = s.replace("\r\n", "\n").replace("\r", "\n")

        # Remove WEBVTT header lines
        s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

        lines = []
        for line in s.split("\n"):
            line = line.strip()
            if not line:
                continue

            # Skip numeric cue indices (SRT)
            if re.fullmatch(r"\d+", line):
                continue

            # Skip timecodes (SRT/VTT)
            if re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", line):
                continue
            if re.search(r"\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}\.\d{3}", line):
                continue

            # Skip VTT cue settings lines like "align:start position:0%"
            if "-->" in line:
                continue

            # Strip simple markup tags
            line = re.sub(r"<[^>]+>", "", line).strip()
            if line:
                lines.append(line)

        text = " ".join(lines)
        text = re.sub(r"\s+", " ", text).strip()
        return text

    def _pick_language(self, captions_by_lang: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
        """
        Choose a 'best' language.
        Adjust this preference order to your needs.
        """
        preferred = ["eng-US", "eng", "en", "en-US"]
        for p in preferred:
            if p in captions_by_lang:
                return p
        # otherwise just pick the first available language
        return next(iter(captions_by_lang.keys()), None)

    # -----------------------------
    # 3) main: return playlist items enriched with transcript text + lines
    # -----------------------------
    def extract_playlist_with_transcripts(
        self,
        playlist_url: str,
        proxy: Optional[str] = None,
        playlist_end: int = 30,
        store_all_languages: bool = False,
    ) -> List[Dict[str, Any]]:
        ydl_opts = {
            "skip_download": True,
            "proxy": proxy,
            "quiet": False,
            "verbose": True,
            "extract_flat": False,          # full metadata, not just URLs
            "nocheckcertificate": True,
            "playlistend": playlist_end,    # ✅ use the parameter instead of hard-coded 1
            "writesubtitles": True,
            "writeautomaticsubtitles": True,
            "writeinfojson": False,
            "sleep_interval": 2,
            "max_sleep_interval": 5,
            "sleep_interval_requests": 1,
            "retries": 2,
            "download_archive": "tiktok_seen.txt",
        }

        with YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(playlist_url, download=False)

        entries = [e for e in (info.get("entries") or []) if e]

        for e in entries:
            # Default fields (always present even if no captions)
            e["transcript_text"] = ""
            e["transcript_lang"] = None

            # ✅ new: structured lines for the chosen language
            e["transcript_lines"] = []

            # ✅ new: optional per-language structured lines
            e["transcript_lines_by_lang"] = {} if store_all_languages else None

            # keep your existing per-language plain-text map
            e["transcripts"] = {} if store_all_languages else None

            captions = self.get_transcript_urls_by_language(e, prefer_requested=False, exts={"vtt", "srt"})
            if not captions:
                continue

            headers = e.get("http_headers") or {}

            if store_all_languages:
                # Fetch all languages (can be slow!)
                for lang, tracks in captions.items():
                    track = tracks[0]
                    try:
                        raw = self._download_text(track["url"], headers=headers, proxy=proxy)

                        # existing: plain text
                        e["transcripts"][lang] = self._vtt_or_srt_to_text(raw)

                        # ✅ new: structured lines
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

                # Optionally set transcript_text + transcript_lines to preferred language
                chosen = self._pick_language({k: v for k, v in captions.items() if v})
                if chosen:
                    e["transcript_lang"] = chosen
                    # if it errored, transcript_text will carry the error string, which is fine for debugging
                    chosen_text = e["transcripts"].get(chosen)
                    if isinstance(chosen_text, str):
                        e["transcript_text"] = chosen_text

                    chosen_lines = e["transcript_lines_by_lang"].get(chosen)
                    if isinstance(chosen_lines, list):
                        e["transcript_lines"] = chosen_lines

            else:
                # Fetch only one best language to minimize network calls
                chosen = self._pick_language(captions)
                if not chosen:
                    continue
                track = captions[chosen][0]  # first available track

                try:
                    raw = self._download_text(track["url"], headers=headers, proxy=proxy)

                    e["transcript_lang"] = chosen
                    e["transcript_text"] = self._vtt_or_srt_to_text(raw)

                    # ✅ new: structured lines
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

        return entries

    def _time_to_ms(self, t: str) -> float:
        parts = t.split(":")
        if len(parts) == 3:  # HH:MM:SS.mmm
            h, m, rest = parts
        else:               # MM:SS.mmm
            h = 0
            m, rest = parts
        s, ms = rest.split(".")
        return (
            int(h) * 3600_000 +
            int(m) * 60_000 +
            int(s) * 1000 +
            int(ms)
        )

    def parse_vtt_to_lines(self, vtt_text: str) -> List[AssetTranscriptLine]:
        """
        Parse VTT/SRT-ish text into structured timed lines.
        """
        lines: List[AssetTranscriptLine] = []
        vtt_text = vtt_text.replace("\r\n", "\n").replace("\r", "\n")

        blocks = vtt_text.split("\n\n")

        for block in blocks:
            block = block.strip()
            if not block or block.startswith("WEBVTT"):
                continue

            rows = block.split("\n")

            # ✅ fix: use the class-level regex
            match = self.TIMECODE_RE.search(block)
            if not match:
                continue

            start_ms = self._time_to_ms(match.group("start"))
            end_ms = self._time_to_ms(match.group("end"))
            duration_ms = max(0.0, end_ms - start_ms)

            # ✅ fix: use class-level regex and strip markup
            text_lines = [
                re.sub(r"<[^>]+>", "", r).strip()
                for r in rows
                if not self.TIMECODE_RE.search(r) and r.strip() and not r.strip().isdigit()
            ]

            if not text_lines:
                continue

            content = " ".join(text_lines)

            lines.append(
                AssetTranscriptLine(
                    offset_ms=start_ms,
                    duration_ms=duration_ms,
                    total_ticks=int(start_ms * self.TICKS_PER_MS),
                    content=content,
                )
            )

        return lines



# import re
# from typing import Any, Dict, List, Optional, Tuple
# import requests
# from yt_dlp import YoutubeDL
# from dataclasses import dataclass

# class TikTokScraper:
    
#     TICKS_PER_MS = 10_000
#     TIMECODE_RE = re.compile(r"(?P<start>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})\s+-->\s+"
#                              r"(?P<end>\d{2}:\d{2}:\d{2}\.\d{3}|\d{2}:\d{2}\.\d{3})" )
    
#     # -----------------------------
#     # 1) caption URL extraction
#     # -----------------------------
#     def get_transcript_urls_by_language(
#         self,
#         info: Dict[str, Any],
#         *,
#         prefer_requested: bool = True,
#         exts: Optional[set[str]] = None,
#     ) -> Dict[str, List[Dict[str, str]]]:
#         if exts is not None:
#             exts = {e.lower().lstrip(".") for e in exts}

#         out: Dict[str, List[Dict[str, str]]] = {}

#         def add_track(lang: str, track: Dict[str, Any], source: str) -> None:
#             url = track.get("url")
#             if not url:
#                 return
#             ext = (track.get("ext") or "").lower().lstrip(".")
#             if exts is not None and ext not in exts:
#                 return
#             item: Dict[str, str] = {"ext": ext or "", "url": url, "source": source}
#             name = track.get("name") or track.get("title")
#             if name:
#                 item["name"] = str(name)
#             out.setdefault(lang, []).append(item)

#         requested = info.get("requested_subtitles") or {}
#         if isinstance(requested, dict):
#             for lang, track in requested.items():
#                 if isinstance(track, dict):
#                     add_track(lang, track, "requested_subtitles")
#             if prefer_requested and out:
#                 return out

#         subtitles = info.get("subtitles") or {}
#         if isinstance(subtitles, dict):
#             for lang, tracks in subtitles.items():
#                 if isinstance(tracks, list):
#                     for t in tracks:
#                         if isinstance(t, dict):
#                             add_track(lang, t, "subtitles")

#         auto = info.get("automatic_captions") or {}
#         if isinstance(auto, dict):
#             for lang, tracks in auto.items():
#                 if isinstance(tracks, list):
#                     for t in tracks:
#                         if isinstance(t, dict):
#                             add_track(lang, t, "automatic_captions")

#         return out

#     # -----------------------------
#     # 2) download + parse caption text
#     # -----------------------------
#     def _download_text(self, url: str, headers: Optional[dict], proxy: Optional[str], timeout: int = 30) -> str:
#         proxies = None
#         if proxy:
#             proxies = {"http": proxy, "https": proxy}

#         r = requests.get(url, headers=headers or {}, proxies=proxies, timeout=timeout)
#         r.raise_for_status()
#         return r.text

#     def _vtt_or_srt_to_text(self, s: str) -> str:
#         """
#         Best-effort conversion of VTT/SRT to readable text:
#         - strips WEBVTT header
#         - strips timestamps and cue indices
#         - strips simple <...> tags
#         - collapses whitespace
#         """
#         if not s:
#             return ""

#         # Normalize newlines
#         s = s.replace("\r\n", "\n").replace("\r", "\n")

#         # Remove WEBVTT header lines
#         s = re.sub(r"^\ufeff?WEBVTT.*?\n", "", s, flags=re.IGNORECASE)

#         lines = []
#         for line in s.split("\n"):
#             line = line.strip()
#             if not line:
#                 continue

#             # Skip numeric cue indices (SRT)
#             if re.fullmatch(r"\d+", line):
#                 continue

#             # Skip timecodes (SRT/VTT)
#             if re.search(r"\d{2}:\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}:\d{2}\.\d{3}", line):
#                 continue
#             if re.search(r"\d{2}:\d{2}\.\d{3}\s+-->\s+\d{2}:\d{2}\.\d{3}", line):
#                 continue

#             # Skip VTT cue settings lines like "align:start position:0%"
#             if "-->" in line:
#                 continue

#             # Strip simple markup tags
#             line = re.sub(r"<[^>]+>", "", line).strip()
#             if line:
#                 lines.append(line)

#         text = " ".join(lines)
#         text = re.sub(r"\s+", " ", text).strip()
#         return text

#     def _pick_language(self, captions_by_lang: Dict[str, List[Dict[str, str]]]) -> Optional[str]:
#         """
#         Choose a 'best' language.
#         Adjust this preference order to your needs.
#         """
#         preferred = ["eng-US", "eng", "en", "en-US"]
#         for p in preferred:
#             if p in captions_by_lang:
#                 return p
#         # otherwise just pick the first available language
#         return next(iter(captions_by_lang.keys()), None)

#     # -----------------------------
#     # 3) main: return playlist items enriched with transcript text
#     # -----------------------------
#     def extract_playlist_with_transcripts(self,
#                                           playlist_url: str,
#                                           proxy: Optional[str] = None,
#                                           playlist_end: int = 30,
#                                           store_all_languages: bool = False,
#                                         ) -> List[Dict[str, Any]]:
#         ydl_opts = {
#             "skip_download": True,
#             "proxy": proxy,
#             "quiet": False,
#             "verbose": True,
#             "extract_flat": False,        # full metadata, not just URLs
#             'nocheckcertificate' : True,            
#             "playlistend": 1,            
#             'writesubtitles' : True,
#             'writeautomaticsubtitles' : True,
#             'writeinfojson' : False,
#             'skip_download' : True,
#             "sleep_interval": 2,
#             "max_sleep_interval": 5,
#             "sleep_interval_requests": 1,
#             "retries": 2,
#             "download_archive": "tiktok_seen.txt"
#         }

#         with YoutubeDL(ydl_opts) as ydl:
#             info = ydl.extract_info(playlist_url, download=False)

#         entries = [e for e in (info.get("entries") or []) if e]

#         for e in entries:
#             # Default fields (always present even if no captions)
#             e["transcript_text"] = ""
#             e["transcript_lang"] = None
#             e["transcripts"] = {} if store_all_languages else None

#             captions = self.get_transcript_urls_by_language(e, prefer_requested=False, exts={"vtt", "srt"})
#             if not captions:
#                 continue

#             headers = e.get("http_headers") or {}

#             if store_all_languages:
#                 # Fetch all languages (can be slow!)
#                 for lang, tracks in captions.items():
#                     # pick first track for that language
#                     track = tracks[0]
#                     try:
#                         raw = self._download_text(track["url"], headers=headers, proxy=proxy)
#                         e["transcripts"][lang] = self._vtt_or_srt_to_text(raw)
#                     except Exception as ex:
#                         e["transcripts"][lang] = f"__error__: {ex}"
#                 # Optionally set transcript_text to preferred language
#                 chosen = self._pick_language({k: v for k, v in captions.items() if v})
#                 if chosen and isinstance(e["transcripts"].get(chosen), str):
#                     e["transcript_lang"] = chosen
#                     e["transcript_text"] = e["transcripts"][chosen]
#             else:
#                 # Fetch only one best language to minimize network calls
#                 chosen = self._pick_language(captions)
#                 if not chosen:
#                     continue
#                 track = captions[chosen][0]  # first available track
#                 try:
#                     raw = self._download_text(track["url"], headers=headers, proxy=proxy)
#                     e["transcript_lang"] = chosen
#                     e["transcript_text"] = self._vtt_or_srt_to_text(raw)
#                 except Exception as ex:
#                     e["transcript_lang"] = chosen
#                     e["transcript_text"] = f"__error__: {ex}"

#         return entries

#     def _time_to_ms(self, t: str) -> float:
#         parts = t.split(":")
#         if len(parts) == 3:  # HH:MM:SS.mmm
#             h, m, rest = parts
#         else:               # MM:SS.mmm
#             h = 0
#             m, rest = parts
#         s, ms = rest.split(".")
#         return (
#             int(h) * 3600_000 +
#             int(m) * 60_000 +
#             int(s) * 1000 +
#             int(ms)
#         )

#     def parse_vtt_to_lines(self, vtt_text: str) -> List[AssetTranscriptLine]:
#         lines: List[AssetTranscriptLine] = []
#         vtt_text = vtt_text.replace("\r\n", "\n").replace("\r", "\n")

#         blocks = vtt_text.split("\n\n")

#         for block in blocks:
#             block = block.strip()
#             if not block or block.startswith("WEBVTT"):
#                 continue

#             rows = block.split("\n")
#             match = TIMECODE_RE.search(block)
#             if not match:
#                 continue

#             start_ms = self._time_to_ms(match.group("start"))
#             end_ms = self._time_to_ms(match.group("end"))
#             duration_ms = max(0, end_ms - start_ms)

#             # Collect text lines after the timestamp
#             text_lines = [
#                 re.sub(r"<[^>]+>", "", r).strip()
#                 for r in rows
#                 if not TIMECODE_RE.search(r) and r.strip() and not r.strip().isdigit()
#             ]

#             if not text_lines:
#                 continue

#             content = " ".join(text_lines)

#             lines.append(
#                 AssetTranscriptLine(
#                     offset_ms=start_ms,
#                     duration_ms=duration_ms,
#                     total_ticks=int(start_ms * 10_000),
#                     content=content,
#                 )
#             )

#         return lines


# @dataclass
# class AssetTranscriptLine:
#     offset_ms: float
#     duration_ms: float
#     total_ticks: int
#     content: str