#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from datetime import datetime

# If you truly need ./modules, keep this; otherwise remove.
BASE_DIR = os.path.dirname(__file__)
MODULE_DIR = os.path.join(BASE_DIR, "modules")
if os.path.isdir(MODULE_DIR) and MODULE_DIR not in sys.path:
    sys.path.append(MODULE_DIR)

# ---- Load env (locally). In Azure, Function App Settings supply env vars. ----
try:
    from loadenv import load_env
    load_env(required_keys=[
        "OPENAI_API_KEY",
        "EMAIL_USER",
        "EMAIL_PASS",
        # Reddit optional
        "REDDIT_CLIENT_ID",
        "REDDIT_CLIENT_SECRET",
        "REDDIT_USER_AGENT",
    ], raise_on_missing=False)
except Exception:
    pass

from technical import get_technical_indicators
from fundamentals import get_fundamentals
from news import fetch_news
from strategy import evaluate_strategy
try:
    from social_monitor import social_snapshot, reddit_healthcheck
except Exception:
    social_snapshot = None
    reddit_healthcheck = None

from summarizer import summarize_insights
try:
    from report_builder import build_html_report
except Exception:
    build_html_report = None
from emailer import send_email

WATCHLIST = [t.strip().upper() for t in os.getenv("TICKERS", "BOA,MSFT,UVIX").split(",") if t.strip()]
RUN_TS = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")

def _social_as_news_item(ticker, social):
    if not social:
        return {"title": f"{ticker} – Social snapshot unavailable", "link": ""}
    title = (f"{ticker} social: mph={social.get('mentions_per_hour')}, "
             f"z_mph={social.get('z_mph')}, "
             f"sent={social.get('avg_sentiment')}, "
             f"pos%={social.get('pos_share')}, neg%={social.get('neg_share')}, "
             f"hype_spike={social.get('hype_spike')}, bearish={social.get('bearish_pressure')}")
    return {"title": title, "link": ""}

def _fallback_html(summaries):
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

def run():
    if callable(reddit_healthcheck):
        try:
            reddit_healthcheck()
        except Exception:
            pass

    summaries = {}
    for ticker in WATCHLIST:
        try:
            ta = get_technical_indicators(ticker)
            fa = get_fundamentals(ticker)
            news_items = fetch_news(ticker) or []
            strat = evaluate_strategy(ticker)
            social = social_snapshot(ticker) if social_snapshot else None
            news_items.append(_social_as_news_item(ticker, social))

            summary_text = summarize_insights(ticker, ta, fa, news_items)

            summaries[ticker] = {
                "summary": summary_text,
                "technical": ta,
                "fundamentals": fa,
                "news": news_items,
                "strategy": strat,
                "social": social,
            }
        except Exception as e:
            summaries[ticker] = {
                "summary": f"⚠️ Error processing {ticker}: {e}",
                "technical": None, "fundamentals": None, "news": [],
                "strategy": None, "social": None,
            }

    html = build_html_report(summaries, run_timestamp=RUN_TS) if callable(build_html_report) else _fallback_html(summaries)
    send_email(html)

if __name__ == "__main__":
    run()