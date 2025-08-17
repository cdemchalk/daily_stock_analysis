#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys
from datetime import datetime
import logging

from azure.identity import DefaultAzureCredential
from azure.keyvault.secrets import SecretClient

# Configure logging for Azure
logging.basicConfig(level=logging.INFO)

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
        "KEY_VAULT_NAME",
    ], raise_on_missing=False)
except Exception as e:
    logging.error(f"Failed to load environment variables: {str(e)}")

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

# Fetch WATCHLIST from Azure Key Vault (Azure) or env var (local)
def get_watchlist_from_key_vault():
    try:
        vault_name = os.getenv("KEY_VAULT_NAME")
        if os.getenv("FUNCTIONS_WORKER_RUNTIME") == "python" and vault_name:
            vault_url = f"https://{vault_name}.vault.azure.net/"
            credential = DefaultAzureCredential()
            client = SecretClient(vault_url=vault_url, credential=credential)
            tickers_str = client.get_secret("Tickers").value
            return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
        else:
            # Local fallback to env var or .env
            tickers_str = os.getenv("TICKERS", "BAC,MSFT,UVIX")
            return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
    except Exception as e:
        logging.error(f"Failed to fetch WATCHLIST from Key Vault: {str(e)}")
        return ["BAC", "MSFT", "UVIX"]  # Fallback to default tickers

WATCHLIST = get_watchlist_from_key_vault()
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
          <td><pre style="white-space:pre-wrap;margin=0">{payload.get('summary','')}</pre></td>
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
    if not WATCHLIST:
        logging.error("No tickers found in WATCHLIST. Skipping execution.")
        return
    logging.info(f"Starting DailyRunner for tickers: {WATCHLIST}")
    if callable(reddit_healthcheck):
        try:
            reddit_healthcheck()
            logging.info("Reddit healthcheck completed")
        except Exception as e:
            logging.error(f"Reddit healthcheck failed: {str(e)}")

    summaries = {}
    for ticker in WATCHLIST:
        try:
            logging.info(f"Processing ticker: {ticker}")
            ta = get_technical_indicators(ticker)
            logging.info(f"Technical indicators for {ticker}: {ta}")
            fa = get_fundamentals(ticker)
            logging.info(f"Fundamentals for {ticker}: {fa}")
            news_items = fetch_news(ticker) or []
            logging.info(f"News items for {ticker}: {len(news_items)}")
            strat = evaluate_strategy(ticker)
            logging.info(f"Strategy for {ticker}: {strat}")
            social = social_snapshot(ticker) if social_snapshot else None
            logging.info(f"Social snapshot for {ticker}: {social}")
            news_items.append(_social_as_news_item(ticker, social))
            summary_text = summarize_insights(ticker, ta, fa, news_items)
            logging.info(f"Summary for {ticker}: {summary_text}")
            summaries[ticker] = {
                "summary": summary_text,
                "technical": ta,
                "fundamentals": fa,
                "news": news_items,
                "strategy": strat,
                "social": social,
            }
        except Exception as e:
            logging.error(f"Error processing {ticker}: {str(e)}")
            summaries[ticker] = {
                "summary": f"⚠️ Error processing {ticker}: {e}",
                "technical": None, "fundamentals": None, "news": [],
                "strategy": None, "social": None,
            }

    logging.info("Generating HTML report")
    html = build_html_report(summaries, run_timestamp=RUN_TS) if callable(build_html_report) else _fallback_html(summaries)
    logging.info("Sending email with report")
    send_email(html)
    logging.info("Email sent successfully")

if __name__ == "__main__":
    run()