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

# from HttpClientUtils import HttpClientProvider
#from ReelExtractor import Extractor

from TikTokCrawlService import ( TikTokCrawlService,
                                 TikTokScraper,
                                 RequestsCaptionFetcher,
                                 CaptionTrackSelector,
                                 TranscriptParser,
                                 TikTokAssetFactory,
                                 CrawlStateRepository,
                                 TikTokAssetRepository )

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


def test_bsky_skraper():
    
    # Trending: https://bsky.app/profile/trending.bsky.app/feed/22983506
    # Single Post: https://bsky.app/profile/intengineering.bsky.social/post/3jymkvt4fy52z

    try:
        from BskyScraper import Skraper
        skraper = Skraper()
        links = skraper.scrape("https://bsky.app/profile/intengineering.bsky.social", PROXY_URL)
        for link in links:
            print(link)
    except Exception as e:
        print(e)


def build_tiktok_crawl_service(es: Elasticsearch, *, state_index: str, asset_index: str, hash_len: int = 32) -> TikTokCrawlService:
    return TikTokCrawlService(
        scraper=TikTokScraper(),
        caption_fetcher=RequestsCaptionFetcher(),
        caption_selector=CaptionTrackSelector(),
        transcript_parser=TranscriptParser(),
        asset_factory=TikTokAssetFactory(hash_len=hash_len),
        state_repo=CrawlStateRepository(es, index=state_index),
        asset_repo=TikTokAssetRepository(es, index=asset_index),
    )

if __name__ == "__main__":

    from elasticsearch7 import Elasticsearch
    
    es = Elasticsearch("http://localhost:9200", request_timeout=30,)
    
    service = build_tiktok_crawl_service(es, state_index="tiktok-crawl-state", asset_index="tiktok-assets", hash_len=32)
    
    target_profile = "@bbc"
    target_profile_url = f"https://www.tiktok.com/{target_profile}"
    
    videos, run_metrics, state = service.crawl_newest_with_es_state(profile=target_profile,
                                                                    playlist_url=target_profile_url,
                                                                    proxy=PROXY_URL,
                                                                    inventory_limit=5,
                                                                    hydrate_cap=5,
                                                                    store_all_languages=False,
                                                                    download_archive="tiktok_seen.txt",
                                                                    save_assets=True,)

    print("Run flags:", run_metrics["flags"])
    print("Inventory:", run_metrics["inventory_count"], "/", run_metrics["requested_inventory"])
    print("Hydrated:", run_metrics["hydrated_success"])
    print("Errors:", run_metrics["hydrated_errors"])
