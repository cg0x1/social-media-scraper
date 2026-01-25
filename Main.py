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

from TikTokScraper import TikTokScraper
from DailyMotionSkraper import Skraper
from TikTokAsset import TikTokAsset
from Utilities import DateUtility

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

if __name__ == "__main__":
    
    from elasticsearch7 import Elasticsearch
    
    es = Elasticsearch("http://localhost:9200", request_timeout=30,)
    
    scraper = TikTokScraper()
    
    (videos, run_metrics, state) = scraper.crawl_newest_with_es_state(es=es,
                                                                      profile="@bbc",
                                                                      playlist_url="https://www.tiktok.com/@bbc",
                                                                      proxy=PROXY_URL,
                                                                      inventory_limit=5,        # cheap listing size
                                                                      hydrate_cap=5,             # max new videos per run
                                                                      store_all_languages=False,  # fastest path
                                                                  )
    
    print("Run flags:", run_metrics["flags"])
    print("Inventory:", run_metrics["inventory_count"], "/", run_metrics["requested_inventory"])
    print("Hydrated:", run_metrics["hydrated_success"])
    print("Errors:", run_metrics["hydrated_errors"])
    
    if videos:
        for v in videos:
            for v in videos:
                es.index(index="tiktok-assets", id=v["id"], document=v,) # important: dedupe by video_id
    else:
        print("no videos were returned")