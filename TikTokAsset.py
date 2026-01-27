from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Union


@dataclass
class TikTokAsset:
    """
    Represents a document stored in the `tiktok-assets` index (dynamic:false).

    Matches the corrected `tiktok-assets` mapping:
      - NO transcript_text / transcript_lines (those live in `tiktok-asset-transcripts`)
      - subtitles is a dict(lang -> url) stored with enabled:false (optional)
      - transcript_hashes is kept here for change detection / idempotency (optional)
    """

    # Identity
    asset_id: str                     # e.g. "tiktok:7599034996917128461"
    id: str                           # raw platform video id

    # Optional identifiers / owner fields
    display_id: Optional[str] = None

    channel: Optional[str] = None
    channel_id: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None

    playlist: Optional[str] = None
    playlist_id: Optional[str] = None
    playlist_title: Optional[str] = None

    # Content
    title: Optional[str] = None
    description: Optional[str] = None
    artists: Optional[Union[str, List[str]]] = None

    # Metrics
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    repost_count: Optional[int] = None

    # Dates / duration
    upload_date: Optional[str] = None          # yyyyMMdd
    timestamp: Optional[str] = None            # ISO string for ES date
    duration: Optional[int] = None

    # Media / urls
    track: Optional[str] = None
    webpage_url: Optional[str] = None
    original_url: Optional[str] = None
    channel_url: Optional[str] = None
    uploader_url: Optional[str] = None
    playlist_webpage_url: Optional[str] = None
    thumbnail: Optional[str] = None

    # Stored but not indexed (enabled:false) — dict[language] -> url
    subtitles: Optional[Dict[str, Any]] = None

    # Transcript metadata ONLY (no transcript_text stored in this index)
    transcript_lang: Optional[str] = None
    transcript_hashes: Optional[Union[str, List[str]]] = None

    # -----------------------------
    # Normalization
    # -----------------------------

    @staticmethod
    def _norm_str_list(val: Union[str, List[str], None]) -> Optional[List[str]]:
        if val is None:
            return None
        if isinstance(val, str):
            s = val.strip()
            return [s] if s else None
        out = [str(x).strip() for x in val if x is not None and str(x).strip()]
        return out or None

    def normalize(self) -> None:
        # artists -> semicolon string (keeps mapping stable; mapping is keyword)
        if isinstance(self.artists, list):
            cleaned = [str(x).strip() for x in self.artists if x is not None and str(x).strip()]
            self.artists = ";".join(cleaned) if cleaned else None

        # transcript_hashes -> list[str] (keyword supports arrays)
        self.transcript_hashes = self._norm_str_list(self.transcript_hashes)

        # subtitles: ensure it's a dict (lang -> url); drop empties
        if self.subtitles is not None:
            if not isinstance(self.subtitles, dict):
                raise TypeError("subtitles must be a dict[str, Any] mapping language -> url")
            cleaned: Dict[str, Any] = {}
            for k, v in self.subtitles.items():
                lang = str(k).strip()
                if not lang:
                    continue
                if v is None:
                    continue
                url = str(v).strip()
                if not url:
                    continue
                cleaned[lang] = url
            self.subtitles = cleaned or None

    # -----------------------------
    # ES serialization
    # -----------------------------

    def to_es_doc(self, *, include_subtitles: bool = False) -> Dict[str, Any]:
        """
        Produce a document compatible with the corrected `tiktok-assets` index mapping.

        IMPORTANT:
        - No transcript_text/transcript_lines are emitted here.
        - With dynamic:false, unknown fields are ignored by ES, but you should still keep
          the payload clean to avoid surprises.
        """
        self.normalize()

        doc: Dict[str, Any] = {
            "asset_id": self.asset_id,
            "id": self.id,
            "display_id": self.display_id,

            "channel": self.channel,
            "channel_id": self.channel_id,
            "uploader": self.uploader,
            "uploader_id": self.uploader_id,

            "playlist": self.playlist,
            "playlist_id": self.playlist_id,
            "playlist_title": self.playlist_title,

            "title": self.title,
            "description": self.description,
            "artists": self.artists,

            "view_count": self.view_count,
            "like_count": self.like_count,
            "comment_count": self.comment_count,
            "repost_count": self.repost_count,

            "upload_date": self.upload_date,
            "timestamp": self.timestamp,
            "duration": self.duration,

            "track": self.track,

            "webpage_url": self.webpage_url,
            "original_url": self.original_url,
            "channel_url": self.channel_url,
            "uploader_url": self.uploader_url,
            "playlist_webpage_url": self.playlist_webpage_url,

            "thumbnail": self.thumbnail,

            "transcript_lang": self.transcript_lang,
            "transcript_hashes": self.transcript_hashes,
        }

        # Strip None values (smaller payload + fewer accidental type issues)
        doc = {k: v for k, v in doc.items() if v is not None}

        if include_subtitles and self.subtitles is not None:
            doc["subtitles"] = self.subtitles

        return doc

    # -----------------------------
    # (Optional) helper: transcript "envelope" fields for transcript index
    # -----------------------------

    def transcript_envelope_fields(self) -> Dict[str, Any]:
        """
        Returns the denormalized fields that are commonly duplicated into
        `tiktok-asset-transcripts` for filtering (asset_id/source_id/etc.).

        NOTE: Your newest transcript mapping includes `source_id` but does NOT include
        platform/channel/uploader/upload_date/webpage_url/timestamp. Only return what
        exists in *your* mapping if you plan to merge dicts.
        """
        return {
            "asset_id": self.asset_id,
            # "source_id": ???  # Only include if you carry source_id on the asset doc.
        }



# from dataclasses import dataclass, field
# from typing import Optional, List, Dict, Any, Union
# from AssetTranscriptLine import AssetTranscriptLine

# @dataclass
# class TikTokAsset:
#     """
#     Represents a Video found on a creator's page.
#     """
#     # System + ES identity
#     asset_id: str              # e.g. "tiktok:7599034996917128461"
#     id: str                    # platform video id (raw), e.g. "7599034996917128461"

#     display_id: Optional[str] = None

#     channel: Optional[str] = None
#     channel_id: Optional[str] = None
#     uploader: Optional[str] = None
#     uploader_id: Optional[str] = None

#     playlist: Optional[str] = None
#     playlist_id: Optional[str] = None
#     playlist_title: Optional[str] = None

#     title: Optional[str] = None
#     description: Optional[str] = None

#     artists: Optional[Union[str, List[str]]] = None

#     view_count: Optional[int] = None
#     like_count: Optional[int] = None
#     comment_count: Optional[int] = None
#     repost_count: Optional[int] = None

#     upload_date: Optional[str] = None  # yyyyMMdd

#     transcript_lang: Optional[str] = None
#     transcript_text: Optional[str] = None
#     transcript_lines: List[AssetTranscriptLine] = field(default_factory=list)

#     duration: Optional[int] = None
#     timestamp: Optional[str] = None  # ISO string for ES date
#     track: Optional[str] = None

#     webpage_url: Optional[str] = None
#     original_url: Optional[str] = None
#     channel_url: Optional[str] = None
#     uploader_url: Optional[str] = None
#     playlist_webpage_url: Optional[str] = None

#     thumbnail: Optional[str] = None

#     subtitles: Optional[Dict[str, Any]] = None

#     def normalize(self) -> None:
#         if isinstance(self.artists, list):
#             self.artists = ";".join(
#                 [str(x).strip() for x in self.artists if x is not None and str(x).strip()]
#             )

#     def to_es_doc(self, *, include_subtitles: bool = False) -> Dict[str, Any]:
#         self.normalize()

#         doc: Dict[str, Any] = {
#             "asset_id": self.asset_id,
#             "id": self.id,
#             "display_id": self.display_id,

#             "channel": self.channel,
#             "channel_id": self.channel_id,
#             "uploader": self.uploader,
#             "uploader_id": self.uploader_id,

#             "playlist": self.playlist,
#             "playlist_id": self.playlist_id,
#             "playlist_title": self.playlist_title,

#             "title": self.title,
#             "description": self.description,
#             "artists": self.artists,

#             "view_count": self.view_count,
#             "like_count": self.like_count,
#             "comment_count": self.comment_count,
#             "repost_count": self.repost_count,

#             "upload_date": self.upload_date,

#             "transcript_lang": self.transcript_lang,
#             "transcript_text": self.transcript_text,
#             "transcript_lines": [l.to_doc() for l in self.transcript_lines],

#             "duration": self.duration,
#             "timestamp": self.timestamp,
#             "track": self.track,

#             "webpage_url": self.webpage_url,
#             "original_url": self.original_url,
#             "channel_url": self.channel_url,
#             "uploader_url": self.uploader_url,
#             "playlist_webpage_url": self.playlist_webpage_url,

#             "thumbnail": self.thumbnail,
#         }

#         doc = {k: v for k, v in doc.items() if v is not None}

#         if include_subtitles and self.subtitles is not None:
#             doc["subtitles"] = self.subtitles

#         return doc
