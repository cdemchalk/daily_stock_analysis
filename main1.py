#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os
import sys
import inspect
from datetime import datetime

# ----- Pathing: add ./modules to sys.path -----
BASE_DIR = os.path.dirname(__file__)
MODULE_DIR = os.path.join(BASE_DIR, "modules")
if MODULE_DIR not in sys.path:
    sys.path.append(MODULE_DIR)

# ----- Load env FIRST (before importing anything that may read env) -----
from loadenv import load_env
load_env(required_keys=[
    "OPENAI_API_KEY",
    "EMAIL_USER",
    "EMAIL_PASS",           # Gmail App Password
    # Reddit (optional; social monitor will still run without)
    "REDDIT_CLIENT_ID",
    "REDDIT_CLIENT_SECRET",
    "REDDIT_USER_AGENT"
], raise_on_missing=False)   # don't hard fail if Reddit keys missing

# ----- Imports that use network/keys -----
from technical import get_technical_indicators
from fundamentals import get_fundamentals
from news import fetch_news
from strategy import evaluate_strategy
try:
    from social_monitor import social_snapshot
except Exception:
    social_snapshot = None  # allow running without social module

# summarizer should lazily read OPENAI_API_KEY at call-time
from summarizer import summarize_insights

# email + optional report builder
try:
    from report_builder import build_html_report
except Exception:
    build_html_report = None
from emailer import send_email


# ========= Config =========
WATCHLIST = ["boa","msft","uvix"]
RUN_TS = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")


def _social_as_news_item(ticker, social):
    """Fold social metrics into a pseudo news item so the summarizer sees it without changing its signature."""
    if not social:
        return {"title": f"{ticker} – Social snapshot unavailable", "link": ""}
    title = (
        f"{ticker} social: mph={social.get('mentions_per_hour')}, "
        f"z_mph={social.get('z_mph')}, "
        f"sent={social.get('avg_sentiment')}, "
        f"pos%={social.get('pos_share')}, neg%={social.get('neg_share')}, "
        f"hype_spike={social.get('hype_spike')}, bearish={social.get('bearish_pressure')}"
    )
    return {"title": title, "link": ""}


def _fallback_html(summaries):
    """Very simple fallback HTML if report_builder.py isn't present."""
    rows = []
    for tkr, payload in summaries.items():
        rows.append(f"""
        <tr>
          <td style="font-weight:600">{tkr}</td>
          <td><pre style="white-space:pre-wrap;margin:0">{payload.get('summary','')}</pre></td>
        </tr>
        """)
    return f"""
    <html><body>
      <h2>Daily Stock Report</h2>
      <div style="color:#666">Generated: {RUN_TS}</div>
      <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;margin-top:12px">
        <thead><tr><th>Ticker</th><th>Summary</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </body></html>
    """
from modules.social_monitor import reddit_healthcheck
reddit_healthcheck()

def run():
    summaries = {}
    for ticker in WATCHLIST:
        try:
            # --- data pulls ---
            ta = get_technical_indicators(ticker)              # dict from your technical.py
            fa = get_fundamentals(ticker)                      # dict from fundamentals.py
            news_items = fetch_news(ticker) or []              # list[{title,link}]

            strat = evaluate_strategy(ticker)                  # dict incl. ATR_14 & signals
            if isinstance(strat, dict) and "error" in strat:
                print(f"⚠️ Strategy error for {ticker}: {strat['error']}")
            else:
                print(f"✅ Strategy for {ticker}: entry={strat.get('entry_signal')} exit={strat.get('exit_signal')} ATR_14={strat.get('ATR_14')}")
            social = social_snapshot(ticker) if social_snapshot else None
            print(f"🔎 Social snapshot for {ticker}: {social.get('samples') if social else 'n/a'} samples")
            # fold social metrics into the news list so summarizer sees context
            news_items.append(_social_as_news_item(ticker, social))

            # --- summarization (keep old signature) ---
            # If you later update summarizer to accept more context, adjust here.
            summary_text = summarize_insights(ticker, ta, fa, news_items)

            # bundle everything for report
            summaries[ticker] = {
                "summary": summary_text,
                "technical": ta,
                "fundamentals": fa,
                "news": news_items,
                "strategy": strat,
                "social": social,
            }

        except Exception as e:
            # soft-fail per ticker, keep going
            summaries[ticker] = {
                "summary": f"⚠️ Error processing {ticker}: {e}",
                "technical": None, "fundamentals": None, "news": [],
                "strategy": None, "social": None,
            }

    # --- build HTML & email ---
    if callable(build_html_report):
        html = build_html_report(summaries, run_timestamp=RUN_TS)  # if your builder accepts kwargs
    else:
        html = _fallback_html(summaries)

    send_email(html)



if __name__ == "__main__":
    # Optional: quick Reddit connectivity test (won't block if missing)
    if callable(reddit_healthcheck):
        try:
            reddit_healthcheck()
        except Exception as e:
            print(f"⚠️ Reddit healthcheck failed (continuing): {e}")
    run()