# import logging
# import os
# import httpx
# from urllib.parse import quote
# import random

# """This class provides a preconfigured httpx client"""
# class HttpClientProvider:

#     LOG_FORMAT = '%(asctime)s - %(name)s - %(levelname)s: %(message)s'
#     INSTAGRAM_DOCUMENT_ID = "8845758582119845" # contst id for post documents instagram.com
#     _logger = None
   

#     _user_agents = [
#         'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36',
#         'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.1.2 Safari/605.1.15',
#         'Mozilla/5.0 (iPhone; CPU iPhone OS 14_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/14.0 Mobile/15E148 Safari/604.1',
#     ]

#     def __init__(self):
#         logging.getLogger("httpx").setLevel(logging.WARNING)
#         logging.basicConfig(format=self.LOG_FORMAT, datefmt='%m/%d/%Y %I:%M:%S %p')
#         _logger = logging.getLogger()
#         _logger.setLevel(logging.DEBUG)

#     try:
#         PORT = int(os.environ.get('SERVER_PORT', '5555'))
#     except ValueError:
#         PORT = 5555

#     # def getProxy(self):
#     #     PROXY_URL = os.environ.get('PROXY_URL',)
#     #     if(PROXY_URL is None):
#     #         self.logger.info('Using no proxy')
#     #         return None
#     #     else:
#     #         currentProxyWithSession = PROXY_URL
#     #         return currentProxyWithSession

#     # Resolve need for SSL: https://github.com/encode/httpx/issues/475
#     def get_http_client(self, proxy_address:str):
#         ssl_context = httpx.create_ssl_context()
#         ssl_context.check_hostname = False
#         ssl_context.verify_mode = 0
            
#         #resp = httpx.get("https://howsmyssl.com/a/check", verify=ssl_context)
#         #tls_version = resp.json()["tls_version"]
#         userAgent = random.choice(self._user_agents)
        
#         httpClient = httpx.Client(
#             headers={
#                 # this is internal ID of an instegram backend app. It doesn't change often.
#                 "x-ig-app-id": "936619743392459",
                
#                 "User-Agent": userAgent,
#                 "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
#                 "Accept-Encoding": "gzip, deflate, br",
#                 "Accept": "*/*",
#             },
#             proxy = proxy_address,
#             verify = ssl_context,
#             timeout=httpx.Timeout(20.0)
#         )
#         return httpClient
    
#     def get_default_headers(self):
#         return {
#             "x-ig-app-id": "936619743392459",
#             "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/62.0.3202.94 Safari/537.36",
#             "Accept-Language": "en-US,en;q=0.9,ru;q=0.8",
#             "Accept-Encoding": "gzip, deflate, br",
#             "Accept": "*/*",
#         }
    