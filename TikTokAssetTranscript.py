from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Union
from datetime import datetime, timezone


# -----------------------------
# Nested transcript line
# -----------------------------

@dataclass
class TikTokTranscriptLine:
    """
    Mirrors one entry in `transcript_lines` (nested).
    """

    offset_ms: float
    duration_ms: float

    total_ticks: Optional[int] = None

    content: Optional[str] = None
    content_hash: Optional[str] = None

    def to_doc(self) -> Dict[str, Any]:
        doc: Dict[str, Any] = {
            "offset_ms": self.offset_ms,
            "duration_ms": self.duration_ms,
            "total_ticks": self.total_ticks,
            "content": self.content,
            "content_hash": self.content_hash,
        }
        return {k: v for k, v in doc.items() if v is not None}


# -----------------------------
# Root transcript document
# -----------------------------

@dataclass
class TikTokAssetTranscript:
    """
    Represents a document stored in the `tiktok-asset-transcripts` index.

    Mirrors mapping exactly:
      - asset_id (keyword)
      - source_id (keyword)
      - transcript_lang (keyword, lc_norm)
      - transcript_text (text)
      - transcript_hashes (keyword[])
      - transcript_lines (nested)
      - created_at / updated_at (date)
    """

    asset_id: str
    source_id: str

    transcript_lang: Optional[str] = None
    transcript_text: Optional[str] = None

    transcript_hashes: Optional[Union[str, List[str]]] = None
    transcript_lines: List[TikTokTranscriptLine] = field(default_factory=list)

    created_at: Optional[str] = None
    updated_at: Optional[str] = None

    # -----------------------------
    # Normalization
    # -----------------------------

    def normalize(self) -> None:
        """
        Normalize fields to stay compatible with strict ES mapping.
        """
        # transcript_hashes -> list[str]
        if self.transcript_hashes is not None:
            if isinstance(self.transcript_hashes, str):
                self.transcript_hashes = [self.transcript_hashes]
            else:
                self.transcript_hashes = [
                    str(x).strip()
                    for x in self.transcript_hashes
                    if x is not None and str(x).strip()
                ]

        # auto-populate timestamps if missing
        now = datetime.now(timezone.utc).isoformat()
        if self.created_at is None:
            self.created_at = now
        self.updated_at = now

    # -----------------------------
    # ES serialization
    # -----------------------------

    def to_es_doc(self) -> Dict[str, Any]:
        """
        Produce a document compatible with the `tiktok-asset-transcripts` index.
        """
        self.normalize()

        doc: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "source_id": self.source_id,

            "transcript_lang": self.transcript_lang,
            "transcript_text": self.transcript_text,
            "transcript_hashes": self.transcript_hashes,

            "transcript_lines": [l.to_doc() for l in self.transcript_lines],

            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

        # Strip None values to satisfy dynamic:false
        return {k: v for k, v in doc.items() if v is not None}

    # -----------------------------
    # Convenience constructor
    # -----------------------------

    @classmethod
    def from_parts(
        cls,
        *,
        asset_id: str,
        source_id: str,
        transcript_text: str,
        transcript_lines: List[TikTokTranscriptLine],
        transcript_lang: Optional[str] = None,
        transcript_hashes: Optional[Union[str, List[str]]] = None,
    ) -> "TikTokAssetTranscript":
        """
        Helper for building a transcript doc from parsed caption data.
        """
        return cls(
            asset_id=asset_id,
            source_id=source_id,
            transcript_lang=transcript_lang,
            transcript_text=transcript_text,
            transcript_hashes=transcript_hashes,
            transcript_lines=transcript_lines,
        )
