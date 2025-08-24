#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug  9 11:43:07 2025

@author: cdemchalk
"""

import os, re, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any
import logging

import requests
import praw
from nltk.sentiment import SentimentIntensityAnalyzer
from nltk import download as nltk_download

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options", "pennystocks"]
BASELINE_PATH = Path(os.getenv("SOCIAL_BASELINE_PATH", "/tmp/social_baseline.json"))
WINDOW_HOURS = 6
MAX_ITEMS = 300

def _now_utc(): return datetime.now(timezone.utc)

def _ticker_rx(ticker: str):
    # Broad regex to match ticker, company names, and variations
    ticker_patterns = {
        "BAC": r"(\$(BAC|Bank of America)\b|\b(BAC|Bank of America|bankamerica)\b)",
        "MSFT": r"(\$(MSFT|Microsoft)\b|\b(MSFT|Microsoft|ms)\b)",
        "UVIX": r"(\$(UVIX|VIX ETF|Volatility ETF)\b|\b(UVIX|VIX ETF|Volatility ETF|vix)\b)"
    }
    return re.compile(ticker_patterns.get(ticker, rf"(\${ticker}\b|\b{ticker}\b|\b{ticker.lower()}\b)"), re.I)

def _ensure_baseline():
    BASELINE_PATH.parent.mkdir(parents=True, exist_ok=True)
    if not BASELINE_PATH.exists():
        BASELINE_PATH.write_text(json.dumps({}, indent=2))

def _load_baseline():
    _ensure_baseline()
    try: return json.loads(BASELINE_PATH.read_text())
    except Exception: return {}

def _save_baseline(baseline: Dict[str, Any]):
    _ensure_baseline()
    BASELINE_PATH.write_text(json.dumps(baseline, indent=2))

def _z(x, m, s): 
    if not s: return 0.0
    return (x - m) / s

def _reddit_client():
    client_id = os.getenv("REDDIT_CLIENT_ID")
    client_secret = os.getenv("REDDIT_CLIENT_SECRET")
    user_agent = os.getenv("REDDIT_USER_AGENT", "meme-stock-monitor/1.0 by cdemchalk")
    if not client_id or not client_secret:
        logging.warning("Missing REDDIT_CLIENT_ID or REDDIT_CLIENT_SECRET; Reddit data unavailable")
        return None
    try:
        client = praw.Reddit(
            client_id=client_id,
            client_secret=client_secret,
            user_agent=user_agent
        )
        client.subreddit("stocks").new(limit=1)
        logging.info(f"Reddit client initialized: {client}")
        return client
    except Exception as e:
        logging.error(f"Failed to initialize Reddit client: {str(e)} (client_id={client_id[:4]}...)")
        return None

def fetch_reddit_activity(ticker: str) -> List[Dict[str, Any]]:
    cli = _reddit_client()
    if not cli:
        logging.warning(f"No Reddit client for {ticker}; skipping Reddit fetch")
        return []
    rx = _ticker_rx(ticker)
    items = []
    cutoff = _now_utc() - timedelta(hours=24)

    for sub in SUBREDDITS:
        try:
            subreddit = cli.subreddit(sub)
            logging.info(f"Fetching posts for {ticker} from r/{sub}")
            for post in subreddit.new(limit=MAX_ITEMS // len(SUBREDDITS)):
                created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if created < cutoff:
                    continue
                text = (getattr(post, "title", "") + " " + getattr(post, "selftext", "")).lower()
                logging.debug(f"Checking post: {post.title[:50]}...")
                if rx.search(text):
                    items.append({
                        "created": created.isoformat(),
                        "text": text,
                        "source": f"reddit/{sub}",
                        "url": post.url
                    })
            logging.info(f"Found {len(items)} Reddit posts for {ticker} in r/{sub}")
        except Exception as e:
            logging.error(f"Error fetching Reddit activity for {ticker} on r/{sub}: {str(e)}")
            continue

    if not items:
        logging.warning(f"No Reddit posts found for {ticker} in last 24 hours")
    return items

def fetch_stocktwits_activity(ticker: str) -> List[Dict[str, Any]]:
    logging.warning(f"StockTwits fetching disabled for {ticker}; requires API key")
    return []

def compute_sentiment(items: List[Dict[str, Any]]) -> Dict[str, float]:
    try:
        nltk_download("vader_lexicon", quiet=True)
        sia = SentimentIntensityAnalyzer()
        scores = [sia.polarity_scores(i["text"])["compound"] for i in items]
        if not scores:
            return {"avg_sentiment": 0.0, "pos_share": 0.0, "neg_share": 0.0}
        avg = sum(scores) / len(scores)
        pos = sum(1 for s in scores if s > 0.05) / len(scores)
        neg = sum(1 for s in scores if s < -0.05) / len(scores)
        return {
            "avg_sentiment": round(avg, 3),
            "pos_share": round(pos, 3),
            "neg_share": round(neg, 3)
        }
    except Exception as e:
        logging.error(f"Error computing sentiment: {str(e)}")
        return {"avg_sentiment": 0.0, "pos_share": 0.0, "neg_share": 0.0}

def compute_velocity(items: List[Dict[str, Any]]) -> float:
    if not items:
        return 0.0
    try:
        start = min(datetime.fromisoformat(i["created"]) for i in items)
        end = max(datetime.fromisoformat(i["created"]) for i in items)
        hours = max((end - start).total_seconds() / 3600, 1.0)
        return round(len(items) / hours, 2)
    except Exception as e:
        logging.error(f"Error computing velocity: {str(e)}")
        return 0.0

def keyword_flags(items: List[Dict[str, Any]]) -> Dict[str, int]:
    flags = {
        "pump": 0, "dump": 0, "moon": 0, "crash": 0, "short": 0,
        "buy": 0, "sell": 0, "hold": 0, "yolo": 0, "dd": 0,
        "lawsuit": 0, "offering": 0, "downgrade": 0, "bankruptcy": 0
    }
    try:
        for item in items:
            text = item["text"].lower()
            for key in flags:
                if key in text:
                    flags[key] += 1
        return flags
    except Exception as e:
        logging.error(f"Error computing keyword flags: {str(e)}")
        return flags

def update_and_score_baseline(ticker: str, mph: float) -> Dict[str, float]:
    baseline = _load_baseline()
    hist = baseline.get(ticker, [])
    hist.append({"ts": _now_utc().isoformat(), "mph": mph})
    hist = hist[-30:]
    baseline[ticker] = hist
    _save_baseline(baseline)
    vals = [h["mph"] for h in hist[:-1]]
    if len(vals) < 5: return {"z_mph": 0.0, "mean": None, "std": None}
    mean = sum(vals) / len(vals)
    std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
    return {"z_mph": round(_z(mph, mean, std), 3), "mean": round(mean, 3), "std": round(std, 3)}

def social_snapshot(ticker: str) -> Dict[str, Any]:
    logging.info(f"Starting social snapshot for {ticker}")
    r_items = fetch_reddit_activity(ticker)
    s_items = fetch_stocktwits_activity(ticker)
    items = [i for i in [*r_items, *s_items] if "created" in i]

    if not items:
        logging.warning(f"No social items found for {ticker}")
        return {
            "ticker": ticker,
            "samples": 0,
            "mentions_per_hour": 0.0,
            "z_mph": 0.0,
            "avg_sentiment": 0.0,
            "pos_share": 0.0,
            "neg_share": 0.0,
            "keyword_flags": {},
            "hype_spike": False,
            "bearish_pressure": False,
            "recent_examples": [],
            "snippets": []
        }

    sent = compute_sentiment(items)
    mph = compute_velocity(items)
    kf = keyword_flags(items)
    zres = update_and_score_baseline(ticker, mph)

    hype_spike = (zres.get("z_mph", 0) >= 2.0)
    bearish_pressure = sent["neg_share"] > 0.4 and (kf.get("downgrade", 0) + kf.get("lawsuit", 0) + kf.get("offering", 0) > 0)

    recent_snippets = [i["text"][:200] for i in items[:5]]

    logging.info(f"Social snapshot for {ticker}: {len(items)} items found")
    return {
        "ticker": ticker,
        "samples": len(items),
        "mentions_per_hour": mph,
        "z_mph": zres.get("z_mph", 0.0),
        "avg_sentiment": round(sent["avg_sentiment"], 3),
        "pos_share": sent["pos_share"],
        "neg_share": sent["neg_share"],
        "keyword_flags": kf,
        "hype_spike": hype_spike,
        "bearish_pressure": bearish_pressure,
        "recent_examples": items[:10],
        "snippets": recent_snippets
    }

def reddit_healthcheck():
    try:
        cli = _reddit_client()
        if not cli:
            logging.warning("Reddit client unavailable; skipping healthcheck")
            return
        me = cli.read_only
        logging.info(f"Reddit client ready (read_only = {me})")
        logging.info(f"Credentials: client_id={os.getenv('REDDIT_CLIENT_ID')[:4]}..., client_secret={os.getenv('REDDIT_CLIENT_SECRET')[:4]}..., user_agent={os.getenv('REDDIT_USER_AGENT')}")
        next(cli.subreddit("stocks").new(limit=1))
        logging.info("Subreddit access OK")
    except Exception as e:
        logging.error(f"Reddit healthcheck failed: {str(e)}")