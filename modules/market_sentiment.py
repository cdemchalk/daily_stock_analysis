import requests
import logging


def get_market_sentiment(ticker: str) -> dict:
    """Fetch sentiment from StockTwits API (free, no auth required)."""
    logging.info(f"Fetching market sentiment for {ticker}")
    try:
        url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
        headers = {"User-Agent": "Mozilla/5.0 (compatible; StockAnalysis/1.0)"}
        resp = requests.get(url, headers=headers, timeout=10)

        if resp.status_code == 429:
            logging.warning(f"StockTwits rate limited for {ticker}")
            return {
                "ticker": ticker,
                "source": "stocktwits",
                "error": "Rate limited — try again later",
            }

        if resp.status_code != 200:
            logging.warning(f"StockTwits returned {resp.status_code} for {ticker}")
            return {
                "ticker": ticker,
                "source": "stocktwits",
                "error": f"HTTP {resp.status_code}",
            }

        data = resp.json()
        messages = data.get("messages", [])[:30]

        bullish = 0
        bearish = 0
        untagged = 0
        snippets = []

        for msg in messages:
            sentiment = msg.get("entities", {}).get("sentiment", {})
            tag = sentiment.get("basic") if sentiment else None

            if tag == "Bullish":
                bullish += 1
            elif tag == "Bearish":
                bearish += 1
            else:
                untagged += 1

            if len(snippets) < 5:
                body = msg.get("body", "")[:200]
                snippets.append({
                    "text": body,
                    "sentiment": tag or "Untagged",
                    "created_at": msg.get("created_at", ""),
                })

        tagged = bullish + bearish
        total = bullish + bearish + untagged

        sentiment_score = round((bullish - bearish) / tagged, 3) if tagged > 0 else 0.0
        bullish_ratio = round(bullish / tagged, 3) if tagged > 0 else 0.0
        bearish_ratio = round(bearish / tagged, 3) if tagged > 0 else 0.0

        return {
            "ticker": ticker,
            "source": "stocktwits",
            "total_messages": total,
            "bullish_count": bullish,
            "bearish_count": bearish,
            "untagged_count": untagged,
            "bullish_ratio": bullish_ratio,
            "bearish_ratio": bearish_ratio,
            "sentiment_score": sentiment_score,
            "snippets": snippets,
        }
    except requests.exceptions.Timeout:
        logging.warning(f"StockTwits request timed out for {ticker}")
        return {"ticker": ticker, "source": "stocktwits", "error": "Request timed out"}
    except Exception as e:
        logging.error(f"Error fetching sentiment for {ticker}: {str(e)}")
        return {"ticker": ticker, "source": "stocktwits", "error": str(e)}
