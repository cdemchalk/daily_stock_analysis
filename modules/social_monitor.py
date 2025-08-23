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
    return re.compile(rf"(\${ticker}\b|\b{ticker}\b)", re.I)

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
    return praw.Reddit(
        client_id=os.getenv("REDDIT_CLIENT_ID"),
        client_secret=os.getenv("REDDIT_CLIENT_SECRET"),
        user_agent=os.getenv("REDDIT_USER_AGENT", "meme-stock-monitor/0.1")
        
    )

def fetch_reddit_activity(ticker: str) -> List[Dict[str, Any]]:
    rx = _ticker_rx(ticker)
    cli = _reddit_client()
    logging.info(f"Reddit client initialized for {ticker}: {cli}")
    items, cutoff = [], _now_utc() - timedelta(hours=24)

    for sub in SUBREDDITS:
        try:
            subreddit = cli.subreddit(sub)
            for post in subreddit.new(limit=MAX_ITEMS // len(SUBREDDITS)):
                created = datetime.fromtimestamp(post.created_utc, tz=timezone.utc)
                if created < cutoff:
                    continue
                text = (getattr(post, "title", "") + " " + getattr(post, "selftext", "")).lower()
                if rx.search(text):
                    items.append({
                        "created": created.isoformat(),
                        "text": text,
                        "source": f"reddit/{sub}",
                        "url": post.url
                    })
        except Exception as e:
            logging.error(f"Error fetching Reddit activity for {ticker} on {sub}: {str(e)}")
            continue

    return items

def fetch_stocktwits_activity(ticker: str) -> List[Dict[str, Any]]:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        data = r.json()
        items = []
        cutoff = _now_utc() - timedelta(hours=24)
        for msg in data.get("messages", [])[:MAX_ITEMS]:
            created = datetime.strptime(msg["created_at"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
            if created < cutoff:
                continue
            text = msg.get("body", "").lower()
            if _ticker_rx(ticker).search(text):
                items.append({
                    "created": created.isoformat(),
                    "text": text,
                    "source": "stocktwits",
                    "url": f"https://stocktwits.com/message/{msg['id']}"
                })
        return items
    except Exception as e:
        logging.error(f"Error fetching StockTwits activity for {ticker}: {str(e)}")
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
    r_items = fetch_reddit_activity(ticker)
    s_items = fetch_stocktwits_activity(ticker)
    items = [i for i in [*r_items, *s_items] if "created" in i]

    sent = compute_sentiment(items)
    mph = compute_velocity(items)
    kf = keyword_flags(items)
    zres = update_and_score_baseline(ticker, mph)

    hype_spike = (zres.get("z_mph", 0) >= 2.0)
    bearish_pressure = sent["neg_share"] > 0.4 and (kf.get("downgrade", 0) + kf.get("lawsuit", 0) + kf.get("offering", 0) > 0)

    # Include snippets from top 5 recent examples (truncated to 200 chars)
    recent_snippets = [i["text"][:200] for i in items[:5]]

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
        "snippets": recent_snippets  # Added for V1: snippets passed to prompt
    }

def reddit_healthcheck():
    try:
        cli = _reddit_client()
        me = cli.read_only
        logging.info(f"Reddit client ready (read_only = {me})")
        next(cli.subreddit("stocks").new(limit=1))
        logging.info("Subreddit access OK")
    except Exception as e:
        logging.error(f"Reddit healthcheck failed: {str(e)}")
        raise