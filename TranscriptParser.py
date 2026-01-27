import re
from typing import List, Optional
from TikTokCrawlService import TikTokTranscriptLine, LoggerMixin

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