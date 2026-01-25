from dataclasses import dataclass
from typing import Dict, Any

@dataclass
class AssetTranscriptLine:
    offset_ms: float
    duration_ms: float
    total_ticks: int
    content: str

    def to_doc(self) -> Dict[str, Any]:
        # Keep ES field names exactly as mapped
        return {
            "offset_ms": self.offset_ms,
            "duration_ms": self.duration_ms,
            "total_ticks": self.total_ticks,
            "content": self.content,
        }