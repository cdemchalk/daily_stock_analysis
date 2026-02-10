#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import os, sys, json, argparse
from datetime import datetime, timezone
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
        "KEY_VAULT_NAME",
    ], raise_on_missing=False)
except Exception as e:
    logging.error(f"Failed to load environment variables: {str(e)}")

from technical import get_technical_indicators
from fundamentals import get_fundamentals
from news import fetch_news
from strategy import evaluate_strategy
from summarizer import summarize_insights

try:
    from report_builder import build_html_report
except Exception:
    build_html_report = None

try:
    from options_monitor import get_options_data
except Exception:
    get_options_data = None

try:
    from options_strategy import recommend_strategies
except Exception:
    recommend_strategies = None

try:
    from backtester import backtest_strategy
except Exception:
    backtest_strategy = None

try:
    from backtester_entry_exit import backtest_entry_exit
except Exception:
    backtest_entry_exit = None

try:
    from market_sentiment import get_market_sentiment
except Exception:
    get_market_sentiment = None

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
            # Local fallback to env var
            tickers_str = os.getenv("TICKERS")
            if not tickers_str:
                logging.error("TICKERS environment variable is not set")
                raise ValueError("TICKERS environment variable is not set")
            return [t.strip().upper() for t in tickers_str.split(",") if t.strip()]
    except Exception as e:
        logging.error(f"Failed to fetch WATCHLIST: {str(e)}")
        raise


def _fallback_html(summaries, run_ts):
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
      <div style="color:#666">Generated: {run_ts}</div>
      <table border="1" cellpadding="8" cellspacing="0" style="border-collapse:collapse;margin-top:12px">
        <thead><tr><th>Ticker</th><th>Summary</th></tr></thead>
        <tbody>{''.join(rows)}</tbody>
      </table>
    </body></html>
    """


def run(tickers=None, send_email_flag=True, output_format="html",
        backtest=False, backtest_only=False):
    """Main pipeline orchestrator.

    Args:
        tickers: List of ticker symbols. None = load from Key Vault/env.
        send_email_flag: If True, send email report. If False, return output only.
        output_format: "html" returns HTML string, "json" returns JSON-serializable dict.
        backtest: If True, run backtests after analysis and include in report.
        backtest_only: If True, run backtests only (no email, print to terminal).

    Returns:
        HTML string or dict depending on output_format (only when send_email_flag=False).
    """
    if backtest_only:
        send_email_flag = False
    run_ts = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")

    if tickers is None:
        tickers = get_watchlist_from_key_vault()

    if not tickers:
        logging.error("No tickers found. Skipping execution.")
        return None

    logging.info(f"Starting DailyRunner for tickers: {tickers}")

    summaries = {}
    for ticker in tickers:
        try:
            logging.info(f"Processing ticker: {ticker}")

            # 1. Fundamentals first (provides last_earnings_date for anchored VWAP)
            fa = get_fundamentals(ticker)
            logging.info(f"Fundamentals for {ticker}: done")

            # 2. Technicals with anchored VWAP
            last_earnings = fa.get("last_earnings_date") if fa and not fa.get("error") else None
            ta = get_technical_indicators(ticker, last_earnings_date=last_earnings)
            logging.info(f"Technical indicators for {ticker}: done")

            # 3. News
            news_items = fetch_news(ticker) or []
            logging.info(f"News items for {ticker}: {len(news_items)}")

            # 4. Strategy
            strat = evaluate_strategy(ticker)
            logging.info(f"Strategy for {ticker}: done")

            # 5. Options (with chain data for strategy engine)
            options_data = None
            calls_df = None
            puts_df = None
            if callable(get_options_data):
                try:
                    stock_price = ta.get("price") if ta and not ta.get("error") else None
                    options_data = get_options_data(ticker, stock_price=stock_price, return_chain=True)
                    calls_df = options_data.pop("calls_df", None)
                    puts_df = options_data.pop("puts_df", None)
                    logging.info(f"Options for {ticker}: done")
                except Exception as e:
                    logging.error(f"Options error for {ticker}: {str(e)}")

            # 5b. Options strategy recommendations
            strategy_recs = None
            if callable(recommend_strategies) and options_data and not options_data.get("error"):
                try:
                    strategy_recs = recommend_strategies(options_data, ta, fa, calls_df, puts_df)
                    if strategy_recs:
                        top = strategy_recs[0]
                        logging.info(f"Strategy for {ticker}: {top['strategy_name']} "
                                     f"({top['status']}, {top['confidence']:.0%})")
                except Exception as e:
                    logging.error(f"Strategy engine error for {ticker}: {str(e)}")

            # 5c. Backtesting (optional)
            backtest_results = None
            if (backtest or backtest_only) and strategy_recs:
                backtest_results = {}
                # Backtest top recommended strategy
                if callable(backtest_strategy):
                    try:
                        top_strat_name = strategy_recs[0]["strategy_name"]
                        backtest_results["strategy"] = backtest_strategy(ticker, top_strat_name)
                        logging.info(f"Backtest {top_strat_name} for {ticker}: done")
                    except Exception as e:
                        logging.error(f"Backtest strategy error for {ticker}: {str(e)}")

                # Backtest entry/exit signals
                if callable(backtest_entry_exit):
                    try:
                        backtest_results["entry_exit"] = backtest_entry_exit(ticker)
                        logging.info(f"Backtest entry/exit for {ticker}: done")
                    except Exception as e:
                        logging.error(f"Backtest entry/exit error for {ticker}: {str(e)}")

                if backtest_only:
                    print(f"\n{'='*60}")
                    print(f"BACKTEST RESULTS: {ticker}")
                    print(f"{'='*60}")
                    for k, v in backtest_results.items():
                        print(f"\n--- {k.upper()} ---")
                        if isinstance(v, dict):
                            for vk, vv in v.items():
                                print(f"  {vk}: {vv}")

            # 6. Sentiment
            sentiment_data = None
            if callable(get_market_sentiment):
                try:
                    sentiment_data = get_market_sentiment(ticker)
                    logging.info(f"Sentiment for {ticker}: done")
                except Exception as e:
                    logging.error(f"Sentiment error for {ticker}: {str(e)}")

            # 7. GPT summary (skip if backtest-only)
            if backtest_only:
                summary_text = "Backtest-only mode — GPT summary skipped."
            else:
                summary_text = summarize_insights(
                    ticker, ta, fa, news_items,
                    options=options_data,
                    sentiment=sentiment_data,
                    strategy=strat,
                    options_strategies=strategy_recs,
                )
            logging.info(f"Summary for {ticker}: done")

            summaries[ticker] = {
                "summary": summary_text,
                "technical": ta,
                "fundamentals": fa,
                "news": news_items,
                "strategy": strat,
                "options": options_data,
                "sentiment": sentiment_data,
                "options_strategies": strategy_recs,
                "backtest": backtest_results,
            }
        except Exception as e:
            logging.error(f"Error processing {ticker}: {str(e)}")
            summaries[ticker] = {
                "summary": f"Error processing {ticker}: {e}",
                "technical": None, "fundamentals": None, "news": [],
                "strategy": None, "options": None, "sentiment": None,
                "options_strategies": None, "backtest": None,
            }

    # Output
    if output_format == "json":
        # Make JSON-safe (strip non-serializable objects from news)
        json_safe = {}
        for tkr, data in summaries.items():
            json_safe[tkr] = {
                "summary": data.get("summary"),
                "technical": data.get("technical"),
                "fundamentals": data.get("fundamentals"),
                "strategy": data.get("strategy"),
                "options": data.get("options"),
                "sentiment": data.get("sentiment"),
                "options_strategies": data.get("options_strategies"),
                "backtest": data.get("backtest"),
                "news": [{"title": n.get("title", ""), "link": n.get("link", "")}
                         for n in (data.get("news") or [])],
            }
        if send_email_flag:
            html = build_html_report(summaries, run_timestamp=run_ts) if callable(build_html_report) else _fallback_html(summaries, run_ts)
            send_email(html)
            logging.info("Email sent successfully")
        return {"run_timestamp": run_ts, "tickers": tickers, "data": json_safe}

    # HTML output
    logging.info("Generating HTML report")
    html = build_html_report(summaries, run_timestamp=run_ts) if callable(build_html_report) else _fallback_html(summaries, run_ts)

    if send_email_flag:
        logging.info("Sending email with report")
        send_email(html)
        logging.info("Email sent successfully")

    return html


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Daily Stock Analysis Pipeline")
    parser.add_argument("tickers", nargs="*", help="Ticker symbols (e.g., COF BAC MSFT)")
    parser.add_argument("--backtest", action="store_true",
                        help="Run backtests and include results in report")
    parser.add_argument("--backtest-only", action="store_true",
                        help="Run backtests only, no email, print to terminal")
    parser.add_argument("--no-email", action="store_true",
                        help="Run analysis without sending email")
    args = parser.parse_args()

    cli_tickers = [t.strip().upper() for t in args.tickers if t.strip()] or None
    should_email = not args.no_email and not args.backtest_only
    run(tickers=cli_tickers, send_email_flag=should_email,
        backtest=args.backtest, backtest_only=args.backtest_only)
