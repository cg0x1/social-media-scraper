from dataclasses import dataclass, field
from typing import Optional, List, Dict, Any
from AssetTranscriptLine import AssetTranscriptLine

@dataclass
class TikTokAsset:
    """
    Mirrors the tiktok-videos-v1 ES mapping (the fields you actually keep/index/store).
    Notes:
    - artists is stored as a semicolon-delimited string (per your requirement).
    - subtitles can be stored, but it's not in the v1 mapping we built earlier; include if you want it stored.
      If you keep dynamic:false, you must map it or drop it before indexing.
    """
    
    def __init__(self):
        pass

    # IDs
    id: str
    display_id: Optional[str] = None

    # Identity
    channel: Optional[str] = None
    channel_id: Optional[str] = None
    uploader: Optional[str] = None
    uploader_id: Optional[str] = None

    # Playlist/profile
    playlist: Optional[str] = None
    playlist_id: Optional[str] = None
    playlist_title: Optional[str] = None

    # Text
    title: Optional[str] = None
    description: Optional[str] = None

    # Artists (flattened)
    artists: Optional[str] = None  # "A;B;C"

    # Stats
    view_count: Optional[int] = None
    like_count: Optional[int] = None
    comment_count: Optional[int] = None
    repost_count: Optional[int] = None

    # Date
    upload_date: Optional[str] = None  # yyyyMMdd

    # Transcript
    transcript_lang: Optional[str] = None
    transcript_text: Optional[str] = None
    transcript_lines: List[AssetTranscriptLine] = field(default_factory=list)

    # Non-indexed-but-stored fields from your mapping
    duration: Optional[int] = None
    timestamp: Optional[int] = None
    track: Optional[str] = None

    webpage_url: Optional[str] = None
    original_url: Optional[str] = None
    channel_url: Optional[str] = None
    uploader_url: Optional[str] = None
    playlist_webpage_url: Optional[str] = None

    thumbnail: Optional[str] = None

    # Optional: keep subtitles in the object for app use,
    # BUT be careful with ES mapping dynamic:false (see notes below)
    subtitles: Optional[Dict[str, List[Dict[str, str]]]] = None

    def normalize(self) -> None:
        """
        Enforce your storage rules before indexing.
        - artists: if accidentally set as list, flatten to ';'
        - strip very large/ignored fields if present
        """
        if isinstance(self.artists, list):
            self.artists = ";".join([str(x).strip() for x in self.artists if x is not None and str(x).strip()])

    def to_es_doc(self, include_subtitles: bool = True) -> Dict[str, Any]:
        """
        Convert to an ES-ready dict matching tiktok-videos-v1 mapping.
        include_subtitles:
          - If your index mapping includes subtitles (enabled:false or mapped), set True.
          - If mapping is dynamic:false and subtitles NOT mapped, keep False (default).
        """
        self.normalize()

        doc: Dict[str, Any] = {
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

            # stored but not indexed
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

        # Remove None values to reduce payload size
        doc = {k: v for k, v in doc.items() if v is not None}

        if include_subtitles and self.subtitles is not None:
            doc["subtitles"] = self.subtitles

        return doc