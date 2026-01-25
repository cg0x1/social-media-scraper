from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass(frozen=True)
class TikTokAssetMapperOptions:
    hash_len: int = 32
    ensure_asset_id: bool = True


class TikTokAssetMapper:
    _ws = re.compile(r"\s+")

    def __init__(self, options: Optional[TikTokAssetMapperOptions] = None):
        self.options = options or TikTokAssetMapperOptions()

    def canonical_line(self, s: str) -> str:
        s = (s or "").strip()
        s = self._ws.sub(" ", s)
        return s.lower()

    def content_hash(self, s: str) -> str:
        canon = self.canonical_line(s).encode("utf-8")
        return hashlib.sha256(canon).hexdigest()[: self.options.hash_len]

    def enrich_asset_doc_inplace(self, doc: Dict[str, Any]) -> Dict[str, Any]:
        """
        Mutates doc:
          - ensures asset_id
          - adds transcript_lines[*].content_hash
          - adds top-level transcript_hashes
          - coerces transcript offsets/durations to int
        """
        if self.options.ensure_asset_id:
            doc["asset_id"] = self._ensure_asset_id(doc)

        self._enrich_transcripts(doc)
        return doc

    # --- internals ---

    def _ensure_asset_id(self, doc: Dict[str, Any]) -> str:
        if doc.get("asset_id"):
            return doc["asset_id"]
        vid = doc.get("id") or doc.get("display_id")
        if not vid:
            raise ValueError("Cannot build asset_id: missing id/display_id")
        return f"tiktok:{vid}"

    def _enrich_transcripts(self, doc: Dict[str, Any]) -> None:
        lines = doc.get("transcript_lines") or []
        if not isinstance(lines, list):
            return

        hashes = set()
        for line in lines:
            if not isinstance(line, dict):
                continue

            txt = line.get("content") or ""
            h = self.content_hash(txt)
            line["content_hash"] = h
            hashes.add(h)

            # mapping expects integer
            if "offset_ms" in line and line["offset_ms"] is not None:
                line["offset_ms"] = int(line["offset_ms"])
            if "duration_ms" in line and line["duration_ms"] is not None:
                line["duration_ms"] = int(line["duration_ms"])
            if "total_ticks" in line and line["total_ticks"] is not None:
                line["total_ticks"] = int(line["total_ticks"])

        doc["transcript_lines"] = lines
        doc["transcript_hashes"] = sorted(hashes)
