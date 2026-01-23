from HttpClientUtils import HttpClientProvider
from bs4 import BeautifulSoup
class Skraper:
    
    def __init__(self):
        pass

    def scrape(self, target_url:str, proxy:str):
        try:
            provider = HttpClientProvider()
            httpClient = provider.get_http_client(proxy)
            response = httpClient.get(url=target_url, follow_redirects=True, headers=provider.get_default_headers())
            soup = BeautifulSoup(response.text, 'lxml')
            links = soup.find_all('a')
            return links
        except Exception as e:
            print(e)
            raise e
        finally:
            if httpClient is not None:
                httpClient.close()
                httpClient = None