from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TikTokSource:
    """
    Represents a document stored in the `tiktok-sources` index (dynamic: strict).

    Matches mapping:
      - source_id (keyword)
      - tiktok_user_id (keyword)
      - handle (keyword, lc_norm)
      - display_name (text + keyword)
      - profile_url (keyword)
      - description (text + keyword)
      - following_count/follower_count/like_count/video_count/repost_count (long)
      - status (keyword)
      - first_seen/last_seen/index_date/updated_at (date; store ISO-8601 strings)
      - signals (strict object): website_domains, youtube_channel_ids, instagram_usernames,
                                twitter_usernames, emails
    """

    # system unique identifier
    source_id: str
    
    """
    This the authoritative TikTok identifier.
    
    1) It never changes; Protection from identity drift.
    2) TikTok internally uses it to associate videos to accounts
    3) Assets already reference this ID (implicitly or explicitly)
    """
    tiktok_user_id: Optional[str] = None

    # Profile fields
    handle: Optional[str] = None
    display_name: Optional[str] = None
    profile_url: Optional[str] = None
    description: Optional[str] = None

    # Counters (ES long)
    following_count: Optional[int] = None
    follower_count: Optional[int] = None
    like_count: Optional[int] = None
    video_count: Optional[int] = None
    repost_count: Optional[int] = None

    # Status + timestamps (ISO-8601 recommended)
    status: Optional[str] = None
    first_seen: Optional[str] = None
    last_seen: Optional[str] = None
    index_date: Optional[str] = None
    updated_at: Optional[str] = None

    # Signals: keep as lists; ES keyword fields accept arrays naturally
    signals: Dict[str, List[str]] = field(default_factory=dict)

    # -----------------------------
    # Normalization helpers
    # -----------------------------

    _ALLOWED_SIGNAL_KEYS = {
        "website_domains",
        "youtube_channel_ids",
        "instagram_usernames",
        "twitter_usernames",
        "emails",
    }

    @staticmethod
    def _norm_list(val: Any) -> List[str]:
        """
        Normalize a value into a de-duped list[str].
        Accepts: None | str | list/tuple/set
        """
        if val is None:
            return []
        if isinstance(val, (list, tuple, set)):
            items = [str(x).strip() for x in val if x is not None and str(x).strip()]
        else:
            s = str(val).strip()
            items = [s] if s else []

        # de-dupe while preserving order
        seen: set[str] = set()
        out: List[str] = []
        for x in items:
            if x not in seen:
                seen.add(x)
                out.append(x)
        return out

    def normalize(self) -> None:
        """
        Enforces strict mapping compatibility:
          - Drops unknown keys in signals
          - Normalizes signal values to list[str]
        """
        normalized: Dict[str, List[str]] = {}
        for k, v in (self.signals or {}).items():
            if k not in self._ALLOWED_SIGNAL_KEYS:
                # dynamic:strict => unknown keys would break indexing
                continue
            vals = self._norm_list(v)
            if vals:
                normalized[k] = vals
        self.signals = normalized

    # -----------------------------
    # ES serialization
    # -----------------------------

    def to_es_doc(self) -> Dict[str, Any]:
        """
        Produce a document compatible with the `tiktok-sources` mapping.
        """
        self.normalize()

        doc: Dict[str, Any] = {
            "source_id": self.source_id,
            "tiktok_user_id": self.tiktok_user_id,

            "handle": self.handle,
            "display_name": self.display_name,
            "profile_url": self.profile_url,
            "description": self.description,

            "following_count": self.following_count,
            "follower_count": self.follower_count,
            "like_count": self.like_count,
            "video_count": self.video_count,
            "repost_count": self.repost_count,

            "status": self.status,

            "first_seen": self.first_seen,
            "last_seen": self.last_seen,
            "index_date": self.index_date,
            "updated_at": self.updated_at,
        }

        # strip None values (keeps payload smaller + avoids accidental type surprises)
        doc = {k: v for k, v in doc.items() if v is not None}

        if self.signals:
            doc["signals"] = self.signals

        return doc

    # -----------------------------
    # Convenience
    # -----------------------------

    @classmethod
    def from_json(cls, data: Dict[str, Any]) -> "TikTokSource":
        """
        Build from a dict that already uses your canonical field names.
        """
        return cls(
            source_id=str(data.get("source_id") or ""),
            tiktok_user_id=data.get("tiktok_user_id"),

            handle=data.get("handle"),
            display_name=data.get("display_name"),
            profile_url=data.get("profile_url"),
            description=data.get("description"),

            following_count=data.get("following_count"),
            follower_count=data.get("follower_count"),
            like_count=data.get("like_count"),
            video_count=data.get("video_count"),
            repost_count=data.get("repost_count"),

            status=data.get("status"),

            first_seen=data.get("first_seen"),
            last_seen=data.get("last_seen"),
            index_date=data.get("index_date"),
            updated_at=data.get("updated_at"),

            signals=data.get("signals") or {},
        )
