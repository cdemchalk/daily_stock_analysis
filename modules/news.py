import requests
from bs4 import BeautifulSoup
import logging

def fetch_news(ticker):
    url = f"https://news.google.com/rss/search?q={ticker}+stock"
    try:
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, "xml")
        items = soup.find_all("item")
        news_items = []
        for item in items[:5]:
            title = item.title.text
            link = item.link.text
            # Fetch full article content
            article_r = requests.get(link, timeout=15)
            article_soup = BeautifulSoup(article_r.text, "html.parser")
            # Extract main content (e.g., all <p> tags; adjust selector for better accuracy)
            content = ' '.join(p.text for p in article_soup.find_all("p") if p.text.strip())
            content = content[:2000]  # Truncate to ~2000 chars to avoid prompt limits
            news_items.append({"title": title, "link": link, "content": content})
        return news_items
    except Exception as e:
        logging.error(f"Error fetching news for {ticker}: {str(e)}")
        return [{"title": f"News fetch error: {e}", "link": "", "content": ""}]