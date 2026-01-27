from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional, Iterable, Dict, List
from elasticsearch7 import Elasticsearch
from elasticsearch7.helpers import bulk

class ElasticUtility:
    
    def __init__():
        pass
    
    def utc_now_iso() -> str:
        return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")

    def account_id(platform: str, platform_account_id: str) -> str:
        # TikTok: platform_account_id == uploader_id
        return f"{platform}:{platform_account_id}"

    def creator_id(slug_or_uuid: str) -> str:
        return f"creator:{slug_or_uuid}"

    def link_id(creator_id_value: str, account_id_value: str) -> str:
        return f"link:{creator_id_value}:{account_id_value}"



    CREATOR_ENTITIES = "tiketok-source-entities"
    CREATOR_ACCOUNTS = "tiktok-sources"
    CREATOR_ACCOUNT_LINKS = "tiktok-source-links"

    def upsert_creator_entity(self,
        es: Elasticsearch,
        *,
        creator_id_value: str,
        canonical_name: str,
        creator_type: str = "unknown",
        aliases: Optional[List[str]] = None,
        external_ids: Optional[Dict[str, Any]] = None,
        notes: Optional[str] = None,
    ) -> None:
        now = self.utc_now_iso()
        doc = {
            "creator_id": creator_id_value,
            "canonical_name": canonical_name,
            "type": creator_type,
            "aliases": aliases or [],
            "external_ids": external_ids or {
                "youtube_channel_id": None,
                "instagram_username": None,
                "twitter_username": None,
                "website_domain": None,
            },
            "notes": notes or "",
            "updated_at": now,
        }

        es.update(
            index=self.CREATOR_ENTITIES,
            id=creator_id_value,
            body={
                "doc": doc,
                "doc_as_upsert": True,
                "upsert": {**doc, "created_at": now},
            },
            refresh=False,
        )

    def upsert_creator_account(self,
        es: Elasticsearch,
        *,
        platform: str,
        platform_account_id_value: str,
        handle: Optional[str],
        display_name: Optional[str],
        profile_url: Optional[str],
        status: str = "active",
        signals: Optional[Dict[str, List[str]]] = None,
        first_seen_iso: Optional[str] = None,
        last_seen_iso: Optional[str] = None,
    ) -> str:
        """
        Returns account_id (deterministic), e.g. tiktok:<uploader_id>
        """
        now = self.utc_now_iso()
        aid = self.account_id(platform, platform_account_id_value)

        doc = {
            "account_id": aid,
            "platform": platform,
            "platform_account_id": platform_account_id_value,
            "handle": handle,
            "display_name": display_name,
            "profile_url": profile_url,
            "status": status,
            "first_seen": first_seen_iso or now,
            "last_seen": last_seen_iso or now,
            "signals": signals or {
                "website_domains": [],
                "youtube_channel_ids": [],
                "instagram_usernames": [],
                "twitter_usernames": [],
                "emails": [],
            },
            "updated_at": now,
        }

        # Keep first_seen stable: only set on insert
        es.update(
            index=self.CREATOR_ACCOUNTS,
            id=aid,
            body={
                "doc": doc,
                "doc_as_upsert": True,
                "upsert": doc,  # contains first_seen=now
            },
            refresh=False,
        )
        return aid

    def upsert_creator_account_link(self,
        es: Elasticsearch,
        *,
        creator_id_value: str,
        account_id_value: str,
        confidence: float,
        status: str = "active",
        signals: Optional[List[Dict[str, Any]]] = None,
        evidence: Optional[Dict[str, Any]] = None,
        approved: bool = False,
        approved_by: Optional[str] = None,
    ) -> str:
        now = self.utc_now_iso()
        lid = self.link_id(creator_id_value, account_id_value)

        doc = {
            "link_id": lid,
            "creator_id": creator_id_value,
            "account_id": account_id_value,
            "confidence": float(confidence),
            "status": status,
            "signals": signals or [],
            "evidence": evidence or {
                "matched_domains": [],
                "matched_youtube_channel_ids": [],
                "bio_similarity": 0.0,
                "handle_similarity": 0.0,
            },
            "updated_at": now,
            "approved": approved,
            "approved_by": approved_by,
            "approved_at": now if approved and approved_by else None,
        }

        es.update(
            index=self.CREATOR_ACCOUNT_LINKS,
            id=lid,
            body={
                "doc": doc,
                "doc_as_upsert": True,
                "upsert": {**doc, "created_at": now},
            },
            refresh=False,
        )
        return lid

    def upsert_graph_from_yt_dlp_video(self,
        es: Elasticsearch,
        *,
        v: Dict[str, Any],
        creator_slug: str,
        creator_canonical_name: str,
    ) -> None:
        # 1) Creator node
        cid = self.creator_id(creator_slug)
        self.upsert_creator_entity(
            es,
            creator_id_value=cid,
            canonical_name=creator_canonical_name,
            creator_type="organization",
        )

        # 2) Account node (TikTok)
        uploader_id = v.get("uploader_id")
        if not uploader_id:
            raise ValueError("yt-dlp dict missing uploader_id")

        handle = ("@" + v["uploader"]) if v.get("uploader") else None
        display_name = v.get("creator")
        profile_url = v.get("uploader_url")

        aid = self.upsert_creator_account(
            es,
            platform="tiktok",
            platform_account_id_value=str(uploader_id),
            handle=handle,
            display_name=display_name,
            profile_url=profile_url,
            status="active",
            signals=None,  # you can enrich later (domains, emails, etc.)
        )

        # 3) Link edge
        # Start with modest confidence; raise it when you have strong signals (domains, verified links, etc.)
        self.upsert_creator_account_link(self,
            es,
            creator_id_value=cid,
            account_id_value=aid,
            confidence=0.60,
            signals=[
                {"type": "seed_link", "value": "manual_or_seeded", "weight": 0.10},
                {"type": "handle", "value": handle or "", "weight": 0.05},
                {"type": "display_name", "value": display_name or "", "weight": 0.05},
            ],
            evidence={
                "matched_domains": [],
                "matched_youtube_channel_ids": [],
                "bio_similarity": 0.0,
                "handle_similarity": 0.0,
            },
            approved=False,
        )

    def bulk_upsert_creator_accounts(self, es: Elasticsearch, docs: List[Dict[str, Any]]) -> None:
        """
        docs must already match the tiktok-sources mapping and include deterministic _id in docs['account_id'].
        """
        actions = []
        for d in docs:
            _id = d["account_id"]
            actions.append({
                "_op_type": "update",
                "_index": self.CREATOR_ACCOUNTS,
                "_id": _id,
                "doc": d,
                "doc_as_upsert": True,
                "upsert": d,
            })
        bulk(es, actions, refresh=False)
