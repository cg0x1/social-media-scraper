from dataclasses import dataclass
from typing import Dict, Any, Optional

@dataclass(frozen=True)
class AssetTranscriptLine_OLD:
    offset_ms: int
    duration_ms: int
    total_ticks: int
    content: str
    content_hash: Optional[str] = None

    def to_doc(self) -> Dict[str, Any]:
        doc = {
            "offset_ms": int(self.offset_ms),
            "duration_ms": int(self.duration_ms),
            "total_ticks": int(self.total_ticks),
            "content": self.content,
        }
        if self.content_hash:
            doc["content_hash"] = self.content_hash
        return doc
