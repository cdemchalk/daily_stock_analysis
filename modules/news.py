import requests
from bs4 import BeautifulSoup

def fetch_news(ticker):
    url = f"https://news.google.com/rss/search?q={ticker}+stock"
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        return [{"title": i.title.text, "link": i.link.text} for i in items[:5]]
    except Exception as e:
        return [{"title": f"News fetch error: {e}", "link": ""}]