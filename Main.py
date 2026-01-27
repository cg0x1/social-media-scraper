######################################################
#
# https://scrapfly.io/blog/how-to-scrape-instagram/
#
######################################################

from datetime import datetime, timezone
import logging
import os
from urllib.parse import quote
from urllib.parse import urlparse, unquote
from SourceMergeDection import *
from SocialSearchService import SocialSearchService

# from HttpClientUtils import HttpClientProvider
#from ReelExtractor import Extractor

from TikTokCrawlService import ( TikTokCrawlService,
                                 TikTokScraper,
                                 RequestsCaptionFetcher,
                                 CaptionTrackSelector,
                                 TranscriptParser,
                                 TikTokAssetFactory,
                                 CrawlStateRepository,
                                 TikTokAssetRepository,
                                 TikTokAssetTranscriptRepository)

#from TikTokScraper import TikTokScraper
# from DailyMotionSkraper import Skraper
# from TikTokAsset import TikTokAsset
# from Utilities import DateUtility

PROXY_URL = os.environ.get('GLOBAL_PROXY_URL') # in system `path` 

#INSTAGRAM_DOCUMENT_ID = "8845758582119845" # contst id for post documents instagram.com

LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s: %(message)s'

logging.basicConfig(format=LOG_FORMAT, datefmt='%m/%d/%Y %I:%M:%S %p')
_logger = logging.getLogger()
_logger.setLevel(logging.DEBUG)

try:
   PORT = int(os.environ.get("SERVER_PORT", "5555"))
except ValueError:
   PORT = 5555


# def test_bsky_skraper():
    
#     # Trending: https://bsky.app/profile/trending.bsky.app/feed/22983506
#     # Single Post: https://bsky.app/profile/intengineering.bsky.social/post/3jymkvt4fy52z

#     try:
#         from BskyScraper import Skraper
#         skraper = Skraper()
#         links = skraper.scrape("https://bsky.app/profile/intengineering.bsky.social", PROXY_URL)
#         for link in links:
#             print(link)
#     except Exception as e:
#         print(e)

def test_source_change():
    
    es = Elasticsearch(["http://localhost:9200"])

    src_account = {
        "account_id": "tiktok:@chasingoz",
        "platform": "tiktok",
        "platform_account_id": "6825750705401807878",
        "handle": "@chasingoz",
        "display_name": "ChasingOz",
        "profile_url": "https://www.tiktok.com/@chasingoz",
        "signals": {
            "website_domains": ["chasingoz.com"],
            "youtube_channel_ids": ["UC1234567890abcdef"],
            "instagram_usernames": ["chasingoz"],
            "twitter_usernames": ["chasingoz"],
            "emails": ["biz@chasingoz.com"]
        },
        "updated_at": now_utc_iso()
    }

    proposals = propose_creator_merges_for_account(
        es,
        creator_accounts_index="tiktok-sources",
        creator_account_links_index="tiktok-source-links",
        creator_id="creator:chasingoz",   # your canonical creator entity id
        src_account_doc=src_account,
        min_confidence=0.70,
        auto_link_confidence=0.85,
        max_candidates=100,
    )

    for p in proposals:
        print(p["confidence"], p["approved"], p["cand_account_id"], p["evidence"])

def test_social_search_service():
    es = Elasticsearch(["http://localhost:9200"])

    svc = SocialSearchService(es)

    results = svc.search_assets_by_transcript(
        "supply chain disruption",
        size=10,
        transcript_lang="en",
        timestamp_gte="now-30d/d"
    )

    for r in results:
        print(r["asset_id"], r["asset"].get("title"))
        for snip in r["transcript_snippets"]:
            print("  -", snip)

def build_tiktok_crawl_service(
    es: Elasticsearch,
    *,
    hash_len: int,
    state_index: str,
    asset_index: str,
    transcript_index: str = "tiktok-asset-transcripts",
) -> TikTokCrawlService:
    return TikTokCrawlService(
        scraper=TikTokScraper(),
        caption_fetcher=RequestsCaptionFetcher(),
        caption_selector=CaptionTrackSelector(),
        transcript_parser=TranscriptParser(),
        asset_factory=TikTokAssetFactory(hash_len=hash_len),
        state_repo=CrawlStateRepository(es, index=state_index),
        asset_repo=TikTokAssetRepository(es, index=asset_index),
        transcript_repo=TikTokAssetTranscriptRepository(es, index=transcript_index),
        discovery_interval_wait_seconds=3.0, #wait interval for each request for a new video
    )

if __name__ == "__main__":

    from TikTokScraper import TikTokScraper_ORIGINAL
    from elasticsearch7 import Elasticsearch
    
    es = Elasticsearch("http://localhost:9200", request_timeout=30,)
    
    service = build_tiktok_crawl_service(es, state_index="tiktok-crawl-state", asset_index="tiktok-assets", hash_len=32)
    
    target_profile = "@donlemon"
    
    target_profile_url = f"https://www.tiktok.com/{target_profile}"
    

    target_source_id = "tiktok:0000000000001"
    
    videos, run_metrics, state = service.crawl_newest_with_es_state(profile=target_profile,
                                                                    playlist_url=target_profile_url,
                                                                    source_id=target_source_id,
                                                                    proxy=PROXY_URL,
                                                                    inventory_limit=5,
                                                                    hydrate_cap=5,                                                                    
                                                                    download_archive="tiktok_seen.txt",
                                                                    save_assets=True,)

    print("Run flags:", run_metrics["flags"])
    print("Inventory:", run_metrics["inventory_count"], "/", run_metrics["requested_inventory"])
    print("Hydrated:", run_metrics["hydrated_success"])
    print("Errors:", run_metrics["hydrated_errors"])


    # t = TikTokScraper_ORIGINAL(hash_len=32)
    # results = t.crawl_newest_with_es_state(es=es,
    #                                         asset_index="tiktok-assets",
    #                                         download_archive="last_seen.txt",
    #                                         hydrate_cap=5,
    #                                         store_all_languages=False,
    #                                         inventory_limit=5,
    #                                         profile=target_profile,
    #                                         playlist_url=target_profile_url,
    #                                         proxy=PROXY_URL)
    # print(t)
