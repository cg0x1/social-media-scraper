from typing import Optional, List, Dict
from dataclasses import dataclass, field, asdict
from AssetTranscriptLine import AssetTranscriptLine
from TikTokAsset import TikTokAsset
from typing import Iterable, Optional
from elasticsearch import Elasticsearch, helpers


class TikTokAssetIndexer:
    def __init__(
        self,
        es_url: str,
        index_name: str = "tiktok-videos-v1",
        *,
        api_key: Optional[str] = None,
        username: Optional[str] = None,
        password: Optional[str] = None,
        verify_certs: bool | str = True,  # True/False or path to CA bundle
        pipeline: Optional[str] = "tiktok_video_ingest_v1",
        timeout: int = 60,
    ) -> None:
        if api_key:
            self.client = Elasticsearch(es_url, api_key=api_key, verify_certs=verify_certs, request_timeout=timeout)
        elif username and password:
            self.client = Elasticsearch(es_url, basic_auth=(username, password), verify_certs=verify_certs, request_timeout=timeout)
        else:
            self.client = Elasticsearch(es_url, verify_certs=verify_certs, request_timeout=timeout)

        self.index_name = index_name
        self.pipeline = pipeline

    def index_one(self, doc: TikTokAsset, *, include_subtitles: bool = False) -> dict:
        body = doc.to_es_doc(include_subtitles=include_subtitles)

        # Use TikTok id as ES _id for de-duplication / idempotency
        resp = self.client.index(
            index=self.index_name,
            id=doc.id,
            document=body,
            pipeline=self.pipeline
        )
        return resp

    def bulk_index(self, docs: Iterable[TikTokAsset], *, include_subtitles: bool = False, chunk_size: int = 500) -> dict:
        def gen_actions():
            for d in docs:
                yield {
                    "_op_type": "index",
                    "_index": self.index_name,
                    "_id": d.id,
                    "pipeline": self.pipeline,
                    "_source": d.to_es_doc(include_subtitles=include_subtitles),
                }

        success, errors = helpers.bulk(self.client, gen_actions(), chunk_size=chunk_size, raise_on_error=False)
        return {"success": success, "errors": errors}
    
    def from_ytdlp_entry(entry: dict) -> TikTokAsset:
        # artists flatten (your requirement)
        artists_val = entry.get("artists")
        if isinstance(artists_val, list):
            artists_val = ";".join([str(x).strip() for x in artists_val if x])

        lines = []
        for l in entry.get("transcript_lines") or []:
            lines.append(AssetTranscriptLine(
                offset_ms=float(l["offset_ms"]),
                duration_ms=float(l["duration_ms"]),
                total_ticks=int(l["total_ticks"]),
                content=str(l["content"]),
            ))

        return TikTokAsset( id=str(entry.get("id") or entry.get("display_id")),
                            display_id=entry.get("display_id"),
                            channel=entry.get("channel"),
                            channel_id=entry.get("channel_id"),
                            uploader=entry.get("uploader"),
                            uploader_id=entry.get("uploader_id"),
                            playlist=entry.get("playlist"),
                            playlist_id=entry.get("playlist_id"),
                            playlist_title=entry.get("playlist_title"),
                            title=entry.get("title"),
                            description=entry.get("description"),
                            artists=artists_val,
                            view_count=entry.get("view_count"),
                            like_count=entry.get("like_count"),
                            comment_count=entry.get("comment_count"),
                            repost_count=entry.get("repost_count"),
                            upload_date=entry.get("upload_date"),
                            transcript_lang=entry.get("transcript_lang"),
                            transcript_text=entry.get("transcript_text"),
                            transcript_lines=lines,
                            duration=entry.get("duration"),
                            timestamp=entry.get("timestamp"),
                            track=entry.get("track"),
                            webpage_url=entry.get("webpage_url"),
                            original_url=entry.get("original_url"),
                            channel_url=entry.get("channel_url"),
                            uploader_url=entry.get("uploader_url"),
                            playlist_webpage_url=entry.get("playlist_webpage_url"),

                            thumbnail=entry.get("thumbnail"),

                            # only include if your ES mapping supports it
                            subtitles=entry.get("subtitles"),
        )

