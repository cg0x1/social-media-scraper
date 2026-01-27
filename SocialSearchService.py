from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from elasticsearch7 import Elasticsearch


@dataclass(frozen=True)
class TranscriptHit:
    asset_id: str
    score: float
    highlights: List[str]
    transcript_lang: Optional[str] = None
    timestamp: Optional[str] = None  # ISO string from ES
    uploader_id: Optional[str] = None
    channel_id: Optional[str] = None


class SocialSearchService:
    def __init__(
        self,
        es: Elasticsearch,
        *,
        assets_index: str = "social-source-assets",
        transcripts_index: str = "social-asset-transcripts",
    ) -> None:
        self.es = es
        self.assets_index = assets_index
        self.transcripts_index = transcripts_index

    def search_transcripts(
        self,
        query_text: str,
        *,
        size: int = 25,
        uploader_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        transcript_lang: Optional[str] = None,
        timestamp_gte: Optional[str] = None,
        timestamp_lte: Optional[str] = None,
    ) -> List[TranscriptHit]:
        filters: List[Dict[str, Any]] = []

        if uploader_id:
            filters.append({"term": {"uploader_id": uploader_id}})
        if channel_id:
            filters.append({"term": {"channel_id": channel_id}})
        if transcript_lang:
            filters.append({"term": {"transcript_lang": transcript_lang}})
        if timestamp_gte or timestamp_lte:
            rng: Dict[str, Any] = {}
            if timestamp_gte:
                rng["gte"] = timestamp_gte
            if timestamp_lte:
                rng["lte"] = timestamp_lte
            filters.append({"range": {"timestamp": rng}})

        body: Dict[str, Any] = {
            "size": size,
            "_source": ["asset_id", "uploader_id", "channel_id", "timestamp", "upload_date", "transcript_lang"],
            "query": {
                "bool": {
                    "must": [
                        {
                            "match": {
                                "transcript_text": {
                                    "query": query_text,
                                    "operator": "and",
                                }
                            }
                        }
                    ],
                    "filter": filters,
                }
            },
            "highlight": {
                "fields": {
                    "transcript_text": {"fragment_size": 180, "number_of_fragments": 3}
                }
            },
        }

        resp = self.es.search(index=self.transcripts_index, body=body)

        hits: List[TranscriptHit] = []
        for h in resp.get("hits", {}).get("hits", []):
            src = h.get("_source", {}) or {}
            highlights = (h.get("highlight", {}) or {}).get("transcript_text", []) or []
            asset_id = src.get("asset_id") or h.get("_id")
            hits.append(
                TranscriptHit(
                    asset_id=str(asset_id),
                    score=float(h.get("_score") or 0.0),
                    highlights=[str(x) for x in highlights],
                    transcript_lang=src.get("transcript_lang"),
                    timestamp=src.get("timestamp"),
                    uploader_id=src.get("uploader_id"),
                    channel_id=src.get("channel_id"),
                )
            )
        return hits

    def mget_assets(self, asset_ids: Sequence[str]) -> Dict[str, Dict[str, Any]]:
        """
        Returns {asset_id: asset_doc_source} for found docs.
        """
        if not asset_ids:
            return {}

        resp = self.es.mget(index=self.assets_index, body={"ids": list(asset_ids)})

        out: Dict[str, Dict[str, Any]] = {}
        for d in resp.get("docs", []) or []:
            if not d.get("found"):
                continue
            _id = str(d.get("_id"))
            out[_id] = d.get("_source", {}) or {}
        return out

    def search_assets_by_transcript(
        self,
        query_text: str,
        *,
        size: int = 25,
        uploader_id: Optional[str] = None,
        channel_id: Optional[str] = None,
        transcript_lang: Optional[str] = None,
        timestamp_gte: Optional[str] = None,
        timestamp_lte: Optional[str] = None,
    ) -> List[Dict[str, Any]]:
        """
        Convenience method: transcript search -> mget assets -> merged results.
        Each result includes:
          - asset (from assets index)
          - transcript_snippets (from highlight)
          - transcript_meta (lang/timestamp/score)
        """
        transcript_hits = self.search_transcripts(
            query_text,
            size=size,
            uploader_id=uploader_id,
            channel_id=channel_id,
            transcript_lang=transcript_lang,
            timestamp_gte=timestamp_gte,
            timestamp_lte=timestamp_lte,
        )

        asset_map = self.mget_assets([h.asset_id for h in transcript_hits])

        results: List[Dict[str, Any]] = []
        for h in transcript_hits:
            asset_doc = asset_map.get(h.asset_id)
            if not asset_doc:
                # asset missing, still return transcript hit if you want
                continue

            results.append(
                {
                    "asset_id": h.asset_id,
                    "score": h.score,
                    "transcript_snippets": h.highlights,
                    "transcript_lang": h.transcript_lang,
                    "timestamp": h.timestamp,
                    "asset": asset_doc,
                }
            )

        return results


# -----------------------------
# Indexing & update patterns
# -----------------------------

def index_transcript_once(
    es: Elasticsearch,
    *,
    transcripts_index: str,
    asset_id: str,
    transcript_doc: Dict[str, Any],
) -> None:
    """
    Store transcript as write-once doc. Use create=True to avoid accidental overwrites.
    If you DO want idempotency, switch to op_type='index' and compare transcript_hashes.
    """
    es.index(index=transcripts_index, id=asset_id, document=transcript_doc, op_type="create")


def upsert_asset_rollups(
    es: Elasticsearch,
    *,
    assets_index: str,
    asset_id: str,
    fields: Dict[str, Any],
) -> None:
    """
    Upsert only the mutable/rollup fields (view_count, like_count, metrics_updated_at, etc.).
    Keeps payload small and avoids accidentally sending transcript content.
    """
    es.update(
        index=assets_index,
        id=asset_id,
        body={
            "doc": fields,
            "doc_as_upsert": True
        }
    )
