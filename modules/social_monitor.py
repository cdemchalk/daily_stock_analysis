#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug  9 11:43:07 2025

@author: cdemchalk
"""

#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Created on Sat Aug  9 11:32:38 2025

@author: cdemchalk
"""

import os, re, json
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import List, Dict, Any

import requests
import praw
from nltk.sentiment import SentimentIntensityAnalyzer
from nltk import download as nltk_download

SUBREDDITS = ["wallstreetbets", "stocks", "investing", "options", "pennystocks"]
BASELINE_PATH = Path("data/social_baseline.json")
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
    print(cli)
    items, cutoff = [], _now_utc() - timedelta(hours=24)

    for sub in SUBREDDITS:
        try:
            for s in cli.subreddit(sub).new(limit=MAX_ITEMS):
                created = datetime.fromtimestamp(s.created_utc, tz=timezone.utc)
                if created < cutoff: break
                text = f"{s.title}\n{s.selftext or ''}"
                if rx.search(text):
                    items.append({
                        "source":"reddit_post","subreddit":sub,"id":s.id,
                        "created": created.isoformat(),
                        "title": s.title, "text": s.selftext or "",
                        "score": int(getattr(s,"score",0)),
                        "url": f"https://reddit.com{s.permalink}"
                    })
        except Exception as e:
            items.append({"source":"reddit_error","subreddit":sub,"error":str(e)})

        try:
            for c in cli.subreddit(sub).comments(limit=MAX_ITEMS):
                created = datetime.fromtimestamp(c.created_utc, tz=timezone.utc)
                if created < cutoff: break
                body = c.body or ""
                if rx.search(body):
                    items.append({
                        "source":"reddit_comment","subreddit":sub,"id":c.id,
                        "created": created.isoformat(),
                        "text": body, "score": int(getattr(c,"score",0)),
                        "url": f"https://reddit.com{getattr(c, 'permalink','')}"
                    })
        except Exception as e:
            items.append({"source":"reddit_error","subreddit":sub,"error":str(e)})
    return items

def fetch_stocktwits_activity(ticker: str) -> List[Dict[str, Any]]:
    url = f"https://api.stocktwits.com/api/2/streams/symbol/{ticker}.json"
    try:
        r = requests.get(url, timeout=15)
        r.raise_for_status()
        payload = r.json()
        out = []
        for m in (payload.get("messages") or [])[:MAX_ITEMS]:
            created = datetime.fromisoformat(m["created_at"].replace("Z","+00:00"))
            out.append({
                "source":"stocktwits","id":m["id"],"created":created.isoformat(),
                "text": m.get("body",""),
                "user": m.get("user",{}).get("username",""),
                "like_count": m.get("likes",{}).get("total",0),
                "reshares": m.get("reshares",{}).get("reshared_count",0),
                "url": f"https://stocktwits.com/message/{m['id']}"
            })
        return out
    except Exception as e:
        return [{"source":"stocktwits_error","error":str(e)}]

def compute_sentiment(items: List[Dict[str, Any]]) -> Dict[str, Any]:
    try: nltk_download("vader_lexicon", quiet=True)
    except Exception: pass
    sia = SentimentIntensityAnalyzer()
    vals = []
    for it in items:
        text = (it.get("title","")+" "+it.get("text","")).strip()
        if not text: continue
        s = sia.polarity_scores(text)
        it["sentiment"] = s["compound"]
        vals.append(s["compound"])
    if not vals:
        return {"avg_sentiment":0.0,"pos_share":0.0,"neg_share":0.0}
    pos = sum(1 for v in vals if v > 0.3) / len(vals)
    neg = sum(1 for v in vals if v < -0.3) / len(vals)
    return {"avg_sentiment": sum(vals)/len(vals), "pos_share": round(pos,3), "neg_share": round(neg,3)}

def compute_velocity(items: List[Dict[str, Any]], hours=WINDOW_HOURS) -> float:
    cutoff = _now_utc() - timedelta(hours=hours)
    recent = [i for i in items if "created" in i]
    recent = [i for i in recent if datetime.fromisoformat(i["created"]) >= cutoff]
    return round(len(recent)/max(hours,1), 3)

def keyword_flags(items: List[Dict[str, Any]]) -> Dict[str, int]:
    flags = {"earnings":0,"squeeze":0,"halt":0,"lawsuit":0,"offering":0,"split":0,"upgrade":0,"downgrade":0,"dilution":0,"iv_spike":0}
    for it in items:
        text = (it.get("title","")+" "+it.get("text","")).lower()
        for k in flags.keys():
            if k.replace("_"," ") in text:
                flags[k]+=1
    return flags

def update_and_score_baseline(ticker: str, mph: float) -> Dict[str, float]:
    baseline = _load_baseline()
    hist = baseline.get(ticker, [])
    hist.append({"ts": _now_utc().isoformat(), "mph": mph})
    hist = hist[-30:]
    baseline[ticker] = hist
    _save_baseline(baseline)
    vals = [h["mph"] for h in hist[:-1]]
    if len(vals) < 5: return {"z_mph":0.0, "mean":None, "std":None}
    mean = sum(vals)/len(vals)
    std = (sum((v-mean)**2 for v in vals)/len(vals))**0.5
    return {"z_mph": round(_z(mph, mean, std),3), "mean": round(mean,3), "std": round(std,3)}

def social_snapshot(ticker: str) -> Dict[str, Any]:
    r_items = fetch_reddit_activity(ticker)
    s_items = fetch_stocktwits_activity(ticker)
    items = [i for i in [*r_items, *s_items] if "created" in i]

    sent = compute_sentiment(items)
    mph  = compute_velocity(items)
    kf   = keyword_flags(items)
    zres = update_and_score_baseline(ticker, mph)

    hype_spike = (zres.get("z_mph",0) >= 2.0)
    bearish_pressure = sent["neg_share"] > 0.4 and (kf.get("downgrade",0)+kf.get("lawsuit",0)+kf.get("offering",0) > 0)

    return {
        "ticker": ticker,
        "samples": len(items),
        "mentions_per_hour": mph,
        "z_mph": zres.get("z_mph",0.0),
        "avg_sentiment": round(sent["avg_sentiment"],3),
        "pos_share": sent["pos_share"],
        "neg_share": sent["neg_share"],
        "keyword_flags": kf,
        "hype_spike": hype_spike,
        "bearish_pressure": bearish_pressure,
        "recent_examples": items[:10]
    }
def reddit_healthcheck():
    try:
        cli = _reddit_client()
        me = cli.read_only
        print("✅ Reddit client ready (read_only =", me, ")")
        # Ping one sub quickly
        next(cli.subreddit("stocks").new(limit=1))
        print("✅ Subreddit access OK")
    except Exception as e:
        print("❌ Reddit healthcheck failed:", e)
        raise