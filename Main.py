######################################################
#
# https://scrapfly.io/blog/how-to-scrape-instagram/
#
######################################################

from datetime import datetime, timezone
import logging
import json
import os
import re
from typing import Dict
from urllib.parse import quote
from collections import Counter
from urllib.parse import urlparse, unquote

# from HttpClientUtils import HttpClientProvider
#from ReelExtractor import Extractor

from TikTokScraper import TikTokScraper
from DailyMotionSkraper import Skraper
from TikTokAsset import TikTokAsset
from Utilities import DateUtility


PROXY_URL = os.environ.get('PROXY_URL','http://brd-auth-token:S3RjHj4DNMbr38qLtppBpaybHAShMjtx@pmgr-customer-fb64ae88.brd.superproxy.io:24525')
INSTAGRAM_DOCUMENT_ID = "8845758582119845" # contst id for post documents instagram.com
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
      
    scraper = TikTokScraper()
    
    items = scraper.extract_playlist_with_transcripts("https://www.tiktok.com/@chasingoz",
                                                      proxy = PROXY_URL,
                                                      playlist_end = 1,
                                                      store_all_languages = False,)   # True if you want every language (expensive)

    
    for v in items:
        asset = TikTokAsset()
        id = v.get("id") 
        display_id = v.get("display_id")
        channel = v.get("channel")
        channel_id = v.get("channel_id")
        uploader = v.get("uploader")
        uploader_id = v.get("uploader_id") 
        playlist = v.get("playlist")
        playlist_id = v.get("playlist_id")
        playlist_title = v.get("playlist_title")
        title = v.get("title")
        description = v.get("description")
        artists = v.get("artists") #  "A;B;C"
        view_count = int(v.get("view_count") | 0)
        like_count = int(v.get("like_count") | 0)
        comment_count = int(v.get("comment_count") | 0)
        repost_count = int(v.get("repost_count") | 0)        
        transcript_lang = v.get("transcript_lange")
        transcript_text = v.get("transcript_text")
        
        lines = v.get("transcript_lines")
        transcript_lines = lines or []
        
        
        duration = float(v.get("duration") | 0)        
        track = v.get("track")
        webpage_url = v.get("webpage_url")
        original_url = v.get("original_url")
        channel_url = v.get("channel_url")
        uploader_url = v.get("uploader_url")
        playlist_webpage_url = v.get("playlist_webpage_url")
        thumbnail = v.get("webpage_url")
        
        epoch = v.get("timestamp")
        timestamp = datetime.fromtimestamp(epoch, tz=timezone.utc)
        
        ud = v.get("upload_date")
        if(ud):
            upload_date = datetime.strptime(ud, "%Y%m%d")
        else:
            upload_date = datetime.min
       
       # doc = asset.to_es_doc(v, True)
        
    with open(r".\debug_output\tiktok_videos.json", "a", encoding="utf-8") as f:    
        for entry in items:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")
            
    #print(items[0]["id"], items[0]["transcript_lang"], items[0]["transcript_text"][:200])

    print("done")

    #
    # !!! Not allowed to do Instagram ??!!??
    #

    #from UndetectableScraper import UScraper
    #uscraper = UScraper()

    # |
    # | => TikTok
    # |
    # tokLinks = nd.loop().run_until_complete(uscraper.scrape_undetected_with_script("https://www.tiktok.com/@interestingengineering",
    #                                                                                "[...document.querySelectorAll('a')].filter(f=>f.href.includes('video')).map(m=>m.href)",
    #                                                                                PROXY_URL))
    # with open(r"D:\tiktok.txt", "w") as tiktok_file:
    #     for link in tokLinks:
    #         tiktok_file.write(f"{link}\n")        
    #     print(f"TikTok: {link}")
 
    # |
    # | => Daily Motion
    # |  <get channels> with [...document.querySelectorAll('div')].filter(f=>f.getAttribute('data-testid') == 'video-card-channel-name-link')
    # |
    # uscraper = UScraper()
        
    # extracted_links = uscraper.scrape_dailymotion_videos("https://www.dailymotion.com/category/content-sports")
    
    #newsLinks = nd.loop().run_until_complete(uscraper.scrape_undetected("https://www.dailymotion.com/category/content-sports", PROXY_URL))
    
    # dm_skraper = Skraper()
    
    # if(len(extracted_links) > 2):
    #     for link in extracted_links:
    #         last_segment = urlparse(link).path.split("/")[-1]
    #         vid_metadata = dm_skraper.call_api(last_segment, PROXY_URL)
    #         print(vid_metadata)
    #         # print(f"DailyMotion: {link}")
    #         # with open(r"dailymotion_links.txt", "w") as dm_file:
    #         #     for link in news_links:
    #         #         dm_file.write(f"{link}\n")
    # else:
    #     print("No news links were returned")
    # |
    # | => USA Today
    # |
    # todayLinks = []
    # todayLinks = nd.loop().run_until_complete(uscraper.scrape_undetected_with_script("https://www.usatoday.com/media/latest/videos/news/",
    #                                                                                 "[...document.querySelectorAll('a')].filter(f=>f.href.includes('videos/news/')).map(m=>m.href)",
    #                                                                                 PROXY_URL))
    # for link in todayLinks:
    #     print(f"USA Today: {link}")
    #     with open(r"C:\MyCode\InstagramScraper\debug_output\usa-today.txt", "w") as news_file:
    #         for link in todayLinks:
    #             news_file.write(f"{link}\n")


    ###################################################################################################################################################################################
    #
    # >> Twitter/X - NO GO <<
    #
    # from Twitter import TwitterScraper
    # twitterScraper = TwitterScraper()
    # twitterLinks = nd.loop().run_until_complete(twitterScraper.scrape_undetected("https://x.com/CNN", PROXY_URL))
    # for link in twitterLinks:
    #     print(link)
    ###################################################################################################################################################################################

    
    ###################################################################################################################################################################################
    # |
    # | => WSJ << NOPE >>
    # |
    # from WallStJournal import WSJScraper
    # wsj = WSJScraper()
    # wsjLinks = nd.loop().run_until_complete(wsj.scrape_undetected("https://www.wsj.com/news/latest-headlines?mod=nav_top_section", PROXY_URL))
    # for link in wsjLinks:
    #     print(link)    
    ###################################################################################################################################################################################


    #
    # Testing Network Interception
    #
    # from SimpleGoogleClient import GoogleClient
    # client = GoogleClient()
    # asyncio.run(client.run())
    # print("done")


### >> OLD CODE <<

    # s.scrape("https://www.wsj.com/news/latest-headlines?mod=nav_top_section", PROXY_URL)
    #s.scrape_undetected("https://www.wsj.com/news/latest-headlines", PROXY_URL)

    # from ScrapingBotScraper import Skraper
    # s = Skraper()
    # s.scrape("https://www.instagram.com/cnn", PROXY_URL)
    
    # from ScrapingAnt import AntSkaper
    # s = AntSkaper()
    # links = s.scrape( ["https://www.instagram.com/interestingengineering"] )

    # test_bsky_skraper()

    # userData = scrape_user_by_username("chasingoz")
    # parsed = parse_user(userData)    
    # print(parsed)

    # busted; needs to be fixed
    #posts = scrape_user_posts("1067259270", page_size=3)
    #print(posts)
    
    # busted; needs to be fixed
    #tags = scrape_hashtag_mentions("1067259270", page_limit=3)
    #print(json.dumps(tags, indent=2, ensure_ascii=False))

    #ScrapeWithCamouFox()
    
    # try:
    #     #find_reels()
    #     #from MetadataParser import Parser        
    #     #parser = Parser('https://www.instagram.com/interestingengineering/')
    #     #parser.Parse()
        
    #     from ReelExtractor import Extractor
        
    #     extractor = Extractor()

    #     reel_links = extractor.extract_links('https://www.instagram.com/interestingengineering/reels',
    #                                          'http://brd-auth-token:S3RjHj4DNMbr38qLtppBpaybHAShMjtx@pmgr-customer-fb64ae88.brd.superproxy.io:24525')            
    #     print('done')
    # except Exception as e:
    #     print(e)

    # from PuppeteerScraper import Scraper
    # scraper = Scraper()-
    # result = scraper.scrapeUndetected("https://www.instagram.com/interestingengineering/reels",PROXY_URL)
    
    # from ReelExtractor import Extractor
    # extractor = Extractor()
    # links = extractor.extract_reel_links("https://www.instagram.com/interestingengineering/reels", PROXY_URL)
    
    
    
    # from PuppeteerScraper import PuppetScraper
    # scraper = PuppetScraper()
    # links = asyncio.run(scraper.scrape("https://www.instagram.com/interestingengineering/reels", PROXY_URL))
    # for link in links:
    #     print(link)


    # from InstagramSeleniumScraper import Skrayper
    # s = Skrayper()
    # links = s.scrape("https://www.instagram.com/interestingengineering/reels", PROXY_URL)
    
    
    # from ReelExtractor import Extractor
    # extractor = Extractor()
    # links = extractor.extract_reel_links_with_webdriver("https://www.instagram.com/chasingoz/reels", PROXY_URL)
    
    # extractor.extract_links_with_httpx("https://www.instagram.com/chasingoz/reels", PROXY_URL)
    
    # proxyDictionary = { "http": "http://brd-auth-token:S3RjHj4DNMbr38qLtppBpaybHAShMjtx@pmgr-customer-fb64ae88.brd.superproxy.io:24525",
    #                     "https": "http://brd-auth-token:S3RjHj4DNMbr38qLtppBpaybHAShMjtx@pmgr-customer-fb64ae88.brd.superproxy.io:24525" }    
    # extractor.extract_reels_links2("https://www.instagram.com/chasingoz/reels", proxyDictionary)

###

# def scrape_post(url_or_shortcode: str) -> Dict:
#     """Scrape single Instagram post data"""
#     if "http" in url_or_shortcode:
#         shortcode = url_or_shortcode.split("/p/")[-1].split("/")[0]
#     else:
#         shortcode = url_or_shortcode
#     print(f"scraping instagram post: {shortcode}")

#     variables = quote(json.dumps({
#         'shortcode':shortcode,'fetch_tagged_user_count':None,
#         'hoisted_comment_id':None,'hoisted_reply_id':None
#     }, separators=(',', ':')))
#     body = f"variables={variables}&doc_id={INSTAGRAM_DOCUMENT_ID}"
#     url = "https://www.instagram.com/graphql/query"

#     result = httpx.post(
#         url=url,
#         headers={"content-type": "application/x-www-form-urlencoded"},
#         data=body,
#         proxy=""
#     )
#     data = json.loads(result.content)
#     return data["data"]["xdt_shortcode_media"]

# def parse_user(data: Dict) -> Dict:
#     """Parse instagram user's hidden web dataset for user's data"""
#     #log.debug("parsing user data {}", data['username'])
#     result = jmespath.search(
#         """{
#         name: full_name,
#         username: username,
#         id: id,
#         category: category_name,
#         business_category: business_category_name,
#         phone: business_phone_number,
#         email: business_email,
#         bio: biography,
#         bio_links: bio_links[].url,
#         homepage: external_url,        
#         followers: edge_followed_by.count,
#         follows: edge_follow.count,
#         facebook_id: fbid,
#         is_private: is_private,
#         is_verified: is_verified,
#         profile_image: profile_pic_url_hd,
#         video_count: edge_felix_video_timeline.count,
#         videos: edge_felix_video_timeline.edges[].node.{
#             id: id, 
#             title: title,
#             shortcode: shortcode,
#             thumb: display_url,
#             url: video_url,
#             views: video_view_count,
#             tagged: edge_media_to_tagged_user.edges[].node.user.username,
#             captions: edge_media_to_caption.edges[].node.text,
#             comments_count: edge_media_to_comment.count,
#             comments_disabled: comments_disabled,
#             taken_at: taken_at_timestamp,
#             likes: edge_liked_by.count,
#             location: location.name,
#             duration: video_duration
#         },
#         image_count: edge_owner_to_timeline_media.count,
#         images: edge_felix_video_timeline.edges[].node.{
#             id: id, 
#             title: title,
#             shortcode: shortcode,
#             src: display_url,
#             url: video_url,
#             views: video_view_count,
#             tagged: edge_media_to_tagged_user.edges[].node.user.username,
#             captions: edge_media_to_caption.edges[].node.text,
#             comments_count: edge_media_to_comment.count,
#             comments_disabled: comments_disabled,
#             taken_at: taken_at_timestamp,
#             likes: edge_liked_by.count,
#             location: location.name,
#             accesibility_caption: accessibility_caption,
#             duration: video_duration
#         },
#         saved_count: edge_saved_media.count,
#         collections_count: edge_saved_media.count,
#         related_profiles: edge_related_profiles.edges[].node.username
#     }""",
#         data,
#     )
#     return result

# def parse_post(data: Dict) -> Dict:
#     #print("parsing post data {}", data['xdt_shortcode_media'])
#     result = jmespath.search("""{
#         id: id,
#         shortcode: shortcode,
#         dimensions: dimensions,
#         src: display_url,
#         src_attached: edge_sidecar_to_children.edges[].node.display_url,
#         has_audio: has_audio,
#         video_url: video_url,
#         views: video_view_count,
#         plays: video_play_count,
#         likes: edge_media_preview_like.count,
#         location: location.name,
#         taken_at: taken_at_timestamp,
#         related: edge_web_media_to_related_media.edges[].node.shortcode,
#         type: product_type,
#         video_duration: video_duration,
#         music: clips_music_attribution_info,
#         is_video: is_video,
#         tagged_users: edge_media_to_tagged_user.edges[].node.user.username,
#         captions: edge_media_to_caption.edges[].node.text,
#         related_profiles: edge_related_profiles.edges[].node.username,
#         comments_count: edge_media_to_parent_comment.count,
#         comments_disabled: comments_disabled,
#         comments_next_page: edge_media_to_parent_comment.page_info.end_cursor,
#         comments: edge_media_to_parent_comment.edges[].node.{
#             id: id,
#             text: text,
#             created_at: created_at,
#             owner: owner.username,
#             owner_verified: owner.is_verified,
#             viewer_has_liked: viewer_has_liked,
#             likes: edge_liked_by.count
#         }
#     }""", data)
#     return result

# def scrape_post(url_or_shortcode: str) -> Dict:
#     """Scrape single Instagram post data"""
#     if "http" in url_or_shortcode:
#         shortcode = url_or_shortcode.split("/p/")[-1].split("/")[0]
#     else:
#         shortcode = url_or_shortcode
#     print(f"scraping instagram post: {shortcode}")

#     variables = quote(json.dumps({
#         'shortcode':shortcode,'fetch_tagged_user_count':None,
#         'hoisted_comment_id':None,'hoisted_reply_id':None
#     }, separators=(',', ':')))
#     body = f"variables={variables}&doc_id={INSTAGRAM_DOCUMENT_ID}"
#     url = "https://www.instagram.com/graphql/query"

#     result = httpx.post(
#         url=url,
#         headers={"content-type": "application/x-www-form-urlencoded"},
#         data=body
#     )
#     data = json.loads(result.content)
#     return data["data"]["xdt_shortcode_media"]

# def scrape_user_posts(user_id: str, page_size=12, max_pages: int = None):
#     base_url = "https://www.instagram.com/graphql/query/?query_hash=e769aa130647d2354c40ea6a439bfc08&variables="
#     variables = {
#         "id": user_id,
#         "first": page_size,
#         "after": None,
#     }
#     _page_number = 1
#     provider = HttpClientProvider()
#     client = provider.get_http_client(PROXY_URL)
#     try:
#         while True:
#             finalUrl = base_url + quote(json.dumps(variables))
#             resp = client.get(finalUrl)
#             data = resp.json()
#             posts = data["data"]["user"]["edge_owner_to_timeline_media"]
#             for post in posts["edges"]:
#                 yield parse_post(post["node"])  # note: we're using parse_post function from previous chapter
#             page_info = posts["page_info"]
#             if _page_number == 1:
#                 print(f"scraping total {posts['count']} posts of {user_id}")
#             else:
#                 print(f"scraping page {_page_number}")
#             if not page_info["has_next_page"]:
#                 break
#             if variables["after"] == page_info["end_cursor"]:
#                 break
#             variables["after"] = page_info["end_cursor"]
#             _page_number += 1     
#             if max_pages and _page_number > max_pages:
#                 break
#         return data
#     finally:
#         if client is not None:
#             client.close()

# def scrape_user_by_username(username: str):
#     """Scrape Instagram user's data"""
#     try:
#         provider = HttpClientProvider()
#         client = provider.get_http_client(PROXY_URL)
#         result = client.get(
#             f"https://i.instagram.com/api/v1/users/web_profile_info/?username={username}",
#         )
#         data = json.loads(result.content)
#         return data["data"]["user"]
#     except Exception as e:
#         print(e)
#         raise e
#     finally:
#         if(client is not None):
#             client.close()

# def scrape_hashtag_mentions(user_id:str, page_limit:int=None):
#     try:
#         """find all hashtags user mentioned in their posts"""
#         provider = HttpClientProvider()
#         session = provider.get_http_Client()
#         hashtags = Counter()
#         hashtag_pattern = re.compile(r"#(\w+)")
#         posts = scrape_user_posts(user_id, session=session, page_limit=page_limit)
#         for post in posts:
#             desc = '\n'.join(post['captions'])
#             found = hashtag_pattern.findall(desc)
#             for tag in found:
#                 hashtags[tag] += 1
#         return hashtags
#     finally:
#         if(session is not None):
#             session.close()

# def find_reels() -> Dict:
#     """Find all reels in user's timeline"""
#     try:
#         extractor = Extractor()
#         links = extractor.extractLinks("https://www.instagram.com/interestingengineering/", PROXY_URL)
#         for link in links:
#             if "reels" in link:
#                 print(link)
#     except Exception as e:
#         print('exception')
#         raise

# def test_user_scraping():
    # chasingoz | 8265189187
    # targetUserName = "chasingoz"

    # user = scrape_user_by_username(targetUserName)
    
    # userPosts = scrape_user_posts(user_id= "8265189187", max_pages=3) # don't remember who this id is for: 1067259270
    
    # posts = list(userPosts)
    
    # json_text = json.dumps(posts, indent=2, ensure_ascii=False)
    # try:
    #     with open(r"D:\instagram_posts_{}.json".format(targetUserName),"w",encoding="utf-8") as new_file:
    #         new_file.write(json_text)
    #         new_file.close()
    # except Exception as e:
    #     print(e)