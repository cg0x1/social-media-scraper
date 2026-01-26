from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any, Union
from AssetTranscriptLine import AssetTranscriptLine

@dataclass
class TikTokAsset:
    # System + ES identity
    asset_id: str              # e.g. "tiktok:7599034996917128461"
    id: str                    # platform video id (raw), e.g. "7599034996917128461"

    display_id: Optional[str] = None

    channel: Optional[str] = None
    channel_id: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None

    playlist: Optional[str] = None
    playlist_id: Optional[str] = None
    playlist_title: Optional[str] = None

    title: Optional[str] = None
    description: Optional[str] = None

    artists: Optional[Union[str, List[str]]] = None

    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    repost_count: Optional[int] = None

    upload_date: Optional[str] = None  # yyyyMMdd

    transcript_lang: Optional[str] = None
    transcript_text: Optional[str] = None
    transcript_lines: List[AssetTranscriptLine] = field(default_factory=list)

    duration: Optional[int] = None
    timestamp: Optional[str] = None  # ISO string for ES date
    track: Optional[str] = None

    webpage_url: Optional[str] = None
    original_url: Optional[str] = None
    channel_url: Optional[str] = None
    uploader_url: Optional[str] = None
    playlist_webpage_url: Optional[str] = None

    thumbnail: Optional[str] = None

    subtitles: Optional[Dict[str, Any]] = None

    def normalize(self) -> None:
        if isinstance(self.artists, list):
            self.artists = ";".join(
                [str(x).strip() for x in self.artists if x is not None and str(x).strip()]
            )

    def to_es_doc(self, *, include_subtitles: bool = False) -> Dict[str, Any]:
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

            "transcript_lang": self.transcript_lang,
            "transcript_text": self.transcript_text,
            "transcript_lines": [l.to_doc() for l in self.transcript_lines],

            "duration": self.duration,
            "timestamp": self.timestamp,
            "track": self.track,

            "webpage_url": self.webpage_url,
            "original_url": self.original_url,
            "channel_url": self.channel_url,
            "uploader_url": self.uploader_url,
            "playlist_webpage_url": self.playlist_webpage_url,

            "thumbnail": self.thumbnail,
        }

        doc = {k: v for k, v in doc.items() if v is not None}

        if include_subtitles and self.subtitles is not None:
            doc["subtitles"] = self.subtitles

        return doc
