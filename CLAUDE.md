# daily_stock_analysis — Claude Reference

## Project Overview

**Author:** cdemchalk
**Created:** August 2025
**Repo:** `/mnt/e/github/daily_stock_analysis` (git, branches: `main`, `backup-pre-override`)
**Purpose:** Automated daily stock analysis pipeline deployed on Azure Functions. Runs weekdays at 1:00 PM UTC, analyzing a configurable watchlist of tickers and emailing a styled HTML dashboard report with technical indicators, fundamentals, options analysis, market sentiment, and AI-generated actionable insights. Also supports ad-hoc analysis via HTTP trigger and CLI.
**Status:** Fully operational on Azure as of 2026-02-08.

---

## Architecture

```
daily_stock_analysis/
├── main1.py                        # Orchestrator: loads env, fetches data, builds report, sends email
│                                   # Supports: run(tickers=, send_email_flag=, output_format=)
│                                   # CLI: python main1.py AAPL TSLA NVDA
├── DailyRunner/
│   ├── __init__.py                 # Azure Function entry point (timer trigger), imports main1.run()
│   └── function.json               # Timer trigger config (Mon-Fri 1 PM UTC)
├── StockAnalysisHttp/
│   ├── __init__.py                 # Azure Function HTTP trigger, returns report without email
│   └── function.json               # HTTP trigger config (function-level auth)
├── modules/
│   ├── __init__.py                 # Empty package init
│   ├── loadenv.py                  # Smart env loader: skips .env on Azure, uses dotenv locally
│   ├── technical.py                # 22 technical indicators: EMA, RSI, MACD, Bollinger, SMA50/200,
│   │                               # anchored VWAP, support/resistance, 52-week range, % changes
│   ├── fundamentals.py             # ~22 fields: P/E, marketCap, growth, analyst targets, short interest,
│   │                               # sector, dividendYield, days_to_earnings, last_earnings_date
│   ├── options_monitor.py          # Options chain analysis: ATM IV, premiums, P/C ratio, max pain,
│   │                               # unusual activity, IV skew, daily IV persistence (yfinance, no new deps)
│   ├── options_strategy.py         # 7-strategy options engine: covered call, cash-secured put, bull/bear
│   │                               # call spread, iron condor, protective put, long straddle
│   │                               # Scores conditions, selects strikes from chain, computes risk profiles
│   ├── backtester.py               # Black-Scholes options strategy backtester (numpy only)
│   │                               # Walk-forward simulation using historical OHLCV + BS pricing
│   ├── backtester_entry_exit.py    # Entry/exit signal backtester (RSI/VWAP/EMA crossover validation)
│   ├── market_sentiment.py         # StockTwits API sentiment: bullish/bearish ratio, score, snippets
│   │                               # (replaces social_monitor.py Reddit/PRAW dependency)
│   ├── news.py                     # Google News RSS + full article scraping (truncated to 2000 chars)
│   ├── strategy.py                 # Entry/exit signal evaluator (RSI, VWAP, EMA crossovers, ATR)
│   ├── summarizer.py               # GPT-5 with system prompt, structured input, constrained 300-word output
│   │                               # Output: Verdict, Buy & Hold, Swing Setup, Options Play, Risk Flag
│   │                               # Receives pre-computed strategy recommendation for Options Play section
│   ├── report_builder.py           # Dashboard table + per-ticker detail + options bar + strategy card
│   │                               # + backtest results card + catalyst calendar
│   ├── emailer.py                  # Gmail SMTP sender (SSL, port 465)
│   ├── social_monitor.py           # [LEGACY] Reddit/PRAW sentiment — no longer imported, kept for rollback
│   └── YF.py                       # Standalone yfinance diagnostic script
├── data/
│   ├── social_baseline.json        # [LEGACY] Rolling 30-day social velocity baseline per ticker
│   └── iv_history.csv              # Daily ATM IV snapshots per ticker (auto-generated, grows ~1KB/day)
├── docs/
│   ├── architecture.md             # System architecture diagrams (Mermaid + ASCII)
│   └── whitepaper.md               # Technical white paper
├── .env                            # Local environment secrets
├── .gitignore                      # Excludes .env, __pycache__, .python_packages/, etc.
├── .funcignore                     # Azure deploy exclusions (*.md, .git/, etc.)
├── .github/workflows/
│   └── deploy-azure-func.yaml      # GitHub Actions CI/CD: test + deploy to Azure Functions
├── host.json                       # Azure Functions v2 host config (extension bundle v4.x)
├── requirements.txt                # Python 3.12 dependencies (pinned versions)
└── README.md                       # Stub readme
```

---

## Pipeline Flow

1. **Trigger fires** — Timer (Mon-Fri 1 PM UTC) or HTTP request or CLI
2. Calls `main1.run(tickers=, send_email_flag=, output_format=)`
3. **Watchlist loaded** from Azure Key Vault / `TICKERS` env var / CLI args / HTTP params
4. For each ticker (in order):
   1. `fundamentals.get_fundamentals()` — earnings, dividends, P/E, growth, analyst targets, short interest, sector
   2. `technical.get_technical_indicators(ticker, last_earnings_date=)` — 22 indicators from 1-year daily data with anchored VWAP
   3. `news.fetch_news()` — top 5 Google News RSS items with article content
   4. `strategy.evaluate_strategy()` — entry/exit signals based on technical crossovers
   5. `options_monitor.get_options_data(ticker, stock_price=, return_chain=True)` — IV, premiums, P/C ratio, max pain, unusual activity, skew + raw chain DFs
   5b. `options_strategy.recommend_strategies()` — evaluate 7 strategies, score conditions, select strikes, compute risk profiles
   5c. (if `--backtest`) `backtester.backtest_strategy()` + `backtester_entry_exit.backtest_entry_exit()` — BS-simulated historical validation
   6. `market_sentiment.get_market_sentiment()` — StockTwits bullish/bearish ratio and sentiment score
   7. `summarizer.summarize_insights()` — GPT-5 generates structured 300-word analysis, uses pre-computed strategy recommendation
5. `report_builder.build_html_report()` — Dashboard table + detail + options bar + strategy card + backtest card + catalyst calendar
6. `emailer.send_email()` — sends via Gmail SMTP (timer trigger only; HTTP returns report)

---

## Entry Points

### Timer Trigger (DailyRunner)
- **Schedule:** `0 0 13 * * 1-5` (Mon-Fri 1 PM UTC)
- Calls `run()` with default watchlist, sends email

### HTTP Trigger (StockAnalysisHttp)
- **Auth:** Function-level (`?code=<key>` or `x-functions-key` header)
- **GET:** `?tickers=AAPL,MSFT&format=html|json`
- **POST:** `{"tickers": ["AAPL"], "format": "json"}`
- Returns report without sending email

### CLI
```bash
python main1.py AAPL TSLA NVDA            # ad-hoc with email
python main1.py                             # uses env/Key Vault tickers
python main1.py COF --backtest              # analysis + backtest, sends email
python main1.py COF --backtest-only         # backtest only, prints to terminal
python main1.py COF --no-email              # analysis without email
```

---

## Key Differences from /mnt/e/Financial/ (older copy)

| Feature | Financial/ (old) | daily_stock_analysis/ (current) |
|---------|-----------------|-------------------------------|
| Technical indicators | 5 (EMA9, EMA20, RSI, VWAP, price) | 22 (+ MACD, BB, SMA50/200, support/resistance, etc.) |
| VWAP | Broken (cumulative 6-month) | Anchored from last earnings date |
| Fundamentals | 3 fields (calendar dates) | ~22 fields (P/E, growth, targets, short interest, etc.) |
| Options analysis | None | Full chain: IV, premiums, P/C, max pain, skew |
| Sentiment | Reddit/PRAW + NLTK VADER | StockTwits API (free, no auth needed) |
| GPT prompt | No system message, raw dict dump | System persona, structured input, constrained output |
| GPT output | 500-800 words generic | 300 words: Verdict, Buy & Hold, Swing, Options Play |
| Report | Text blocks | Dashboard table + detail + options bar + catalyst calendar |
| Access | Timer trigger only | Timer + HTTP trigger + CLI |
| Data period | 6 months | 1 year (supports SMA200) |

---

## Azure Deployment

- **Runtime:** Azure Functions v2, Python 3.12
- **Schedule:** `0 0 13 * * 1-5` (every weekday at 1:00 PM UTC)
- **Functions:** DailyRunner (timerTrigger) + StockAnalysisHttp (httpTrigger)
- **Resource Group:** `rg-stocks`
- **Key Vault:** `stockdailyvault20172025`
- **Auth:** `azure-identity` DefaultAzureCredential (Managed Identity on Azure)
- **CI/CD:** GitHub Actions on push to `main` or manual `workflow_dispatch`
  - **Test job:** validates requirements.txt, installs deps, runs pytest
  - **Deploy job:** prebuilds deps into `.python_packages/`, creates `release.zip`, deploys via `Azure/functions-action@v1`
  - **Deployment mode:** `WEBSITE_RUN_FROM_PACKAGE=1`, Oryx build disabled
  - **Secrets required:** `AZURE_CREDENTIALS`, `AZURE_FUNCTIONAPP_NAME`
- **Post-deploy:** sanity check lists both deployed functions

### Manual Deploy from CLI

```bash
pip install --target .python_packages/lib/site-packages -r requirements.txt
echo 'from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)' > .python_packages/lib/site-packages/azure/__init__.py

cd /mnt/e/github/daily_stock_analysis
zip -r /tmp/release.zip host.json main1.py modules/ DailyRunner/ StockAnalysisHttp/ requirements.txt .python_packages/ -x "*.pyc" "__pycache__/*"
az functionapp deployment source config-zip --resource-group rg-stocks --name stock-daily-runner --src /tmp/release.zip

az functionapp restart --name stock-daily-runner --resource-group rg-stocks
az functionapp function list --name stock-daily-runner --resource-group rg-stocks --output table
```

### Manual Function Trigger

```bash
MASTER_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query masterKey -o tsv)

# Timer trigger
curl -s -X POST "https://stock-daily-runner.azurewebsites.net/admin/functions/DailyRunner" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{}'

# HTTP trigger
FUNC_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query "functionKeys.default" -o tsv)
curl "https://stock-daily-runner.azurewebsites.net/api/StockAnalysisHttp?tickers=AAPL&code=$FUNC_KEY"
curl "https://stock-daily-runner.azurewebsites.net/api/StockAnalysisHttp?tickers=AAPL&format=json&code=$FUNC_KEY"
```

---

## Dependencies (requirements.txt)

| Package | Version | Purpose |
|---------|---------|---------|
| azure-functions | ==1.17.0 | Azure Function SDK |
| azure-identity | >=1.13.0 | Key Vault auth (DefaultAzureCredential) |
| azure-keyvault-secrets | >=4.7.0 | Key Vault secret retrieval |
| openai | >=1.30.0 | GPT-5 summarization |
| python-dotenv | >=1.0.1 | Local .env file loading |
| yfinance | ==0.2.65 | Stock data, options chains (pinned) |
| pandas | >=2.2.2,<2.4.0 | Data manipulation (upper-bounded) |
| numpy | ==2.1.3 | Numerical operations (pinned) |
| requests | >=2.32.0 | HTTP (news scraping, StockTwits API) |
| beautifulsoup4 | >=4.12.3 | HTML/RSS parsing |
| praw | >=7.7.1 | [LEGACY] Reddit API client — no longer imported |
| nltk | >=3.9 | [LEGACY] VADER sentiment — no longer imported |
| peewee | ==3.18.2 | ORM (yfinance dependency, pinned) |
| lxml | >=4.9.1 | XML parser |
| html5lib | >=1.1 | HTML parser |
| platformdirs | >=2.0.0 | Platform-specific directories |
| pytz | >=2022.5 | Timezone support |
| frozendict | >=2.3.4 | Immutable dictionaries |
| multitasking | >=0.0.7 | yfinance threading support |

---

## Strategy Logic

### Entry/Exit Signals (strategy.py)

**Entry Signal** (all must be true):
- RSI < 35 (oversold)
- Price < VWAP (below volume-weighted average)
- EMA9 crosses above EMA20 (bullish crossover)

**Exit Signal** (all must be true):
- RSI > 65 (overbought)
- Price > VWAP (above volume-weighted average)
- EMA9 crosses below EMA20 (bearish crossover)

Also computes ATR(14) for volatility context. Uses robust 3-tier data fetching with MultiIndex column normalization.

### Options Strategy Engine (options_strategy.py)

7 defined-risk strategies with weighted condition scoring:

| # | Strategy | When | Key Conditions |
|---|----------|------|----------------|
| 1 | Covered Call | Neutral-bullish, income | Price > SMA50, IV 25-45%, RSI 40-60 |
| 2 | Cash-Secured Put | Bullish on dip | Price near support, IV > 30%, RSI < 40 |
| 3 | Bull Call Spread | Directional up | EMA9 > EMA20, Price > VWAP, IV moderate |
| 4 | Bear Call Spread | Directional down | EMA9 < EMA20, RSI > 65, IV > 40% |
| 5 | Iron Condor | Range-bound | BB width < 0.06, IV 40-70%, RSI 40-60 |
| 6 | Protective Put | Long stock hedge | Price near resistance, earnings within DTE |
| 7 | Long Straddle | Big move expected | Earnings 5-15 days, unusual activity, IV < 50% |

Each strategy scored 0-1 based on weighted conditions. Status: recommended (>=0.60, >=3 met), monitor (>=0.40), avoid.

### Backtesting (backtester.py, backtester_entry_exit.py)

- **Black-Scholes backtester:** Simulates options strategy P&L using BS pricing on 1-year OHLCV data. Walk-forward simulation with technical indicator-based entry/exit.
- **Entry/exit backtester:** Validates RSI/VWAP/EMA crossover signals against historical data.
- Activated via `--backtest` or `--backtest-only` CLI flags.

---

## Environment Variables

| Variable | Purpose | Where Set |
|----------|---------|-----------|
| OPENAI_API_KEY | GPT-5 summarization | .env / Azure App Settings / Key Vault |
| EMAIL_USER | Gmail sender address | .env / Azure App Settings |
| EMAIL_PASS | Gmail App Password | .env / Azure App Settings |
| KEY_VAULT_NAME | Azure Key Vault name (`stockdailyvault20172025`) | .env / Azure App Settings |
| TICKERS | Comma-separated ticker list | .env / Key Vault (secret: "Tickers") |
| FUNCTIONS_WORKER_RUNTIME | Set to `python` by Azure (used to detect Azure environment) | Azure runtime |
| WEBSITE_RUN_FROM_PACKAGE | Set to `1` by CI/CD for zip deployment | Azure App Settings |
| REDDIT_CLIENT_ID | [LEGACY] Reddit API auth — no longer required | .env / Azure App Settings |
| REDDIT_CLIENT_SECRET | [LEGACY] Reddit API auth — no longer required | .env / Azure App Settings |
| REDDIT_USER_AGENT | [LEGACY] Reddit API identifier — no longer required | .env / Azure App Settings |

---

## Azure CLI Access (for Claude Code)

Azure CLI is installed natively in WSL at `/usr/bin/az` (v2.83.0).
Authenticated as `cdemchalk@yahoo.com` on subscription `Azure subscription 1`.

### Useful Commands

```bash
# Function app status
az functionapp show --name stock-daily-runner --resource-group rg-stocks --output table

# List deployed functions (should show DailyRunner + StockAnalysisHttp)
az functionapp function list --name stock-daily-runner --resource-group rg-stocks --output table

# View app settings
az webapp config appsettings list --name stock-daily-runner --resource-group rg-stocks --output table

# Stream live logs
az functionapp log tail --name stock-daily-runner --resource-group rg-stocks

# Query App Insights traces (last 7 days)
az monitor app-insights query --app 45c7a0c4-413d-4c56-af04-0fec9664d66c --analytics-query "traces | where timestamp > ago(7d) | order by timestamp desc | take 30 | project timestamp, message, severityLevel"

# Query App Insights exceptions
az monitor app-insights query --app 45c7a0c4-413d-4c56-af04-0fec9664d66c --analytics-query "exceptions | where timestamp > ago(7d) | order by timestamp desc | take 20 | project timestamp, type, outerMessage"

# Trigger timer function manually
MASTER_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query masterKey -o tsv)
curl -s -X POST "https://stock-daily-runner.azurewebsites.net/admin/functions/DailyRunner" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{}'

# Test HTTP trigger
FUNC_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query "functionKeys.default" -o tsv)
curl "https://stock-daily-runner.azurewebsites.net/api/StockAnalysisHttp?tickers=AAPL&code=$FUNC_KEY"

# Restart function app
az functionapp restart --name stock-daily-runner --resource-group rg-stocks
```

### Azure Resource Details

| Resource | Value |
|----------|-------|
| Function App | `stock-daily-runner` |
| Resource Group | `rg-stocks` |
| Location | Central US |
| App Service Plan | `ASP-rgstocks-8c6b` |
| Host | `stock-daily-runner.azurewebsites.net` |
| Storage Account | `dailystockstorage` |
| Storage Container | `daily-reports` |
| Key Vault | `stockdailyvault20172025` |
| App Insights ID | `45c7a0c4-413d-4c56-af04-0fec9664d66c` |
| Instrumentation Key | `ee779079-74a5-4425-bacb-558d4a177a36` |
| Functions Runtime | v4 (Python) |
| Extension Bundle | v4.31.0 |
| Deploy Mode | `WEBSITE_RUN_FROM_PACKAGE=1`, Oryx disabled |

---

## Known Issues

1. **SECURITY — .env still in repo working tree:** `.gitignore` excludes `.env`, but verify it was never committed to git history.

2. **News module scrapes full articles:** `news.py` follows each news link and scrapes all `<p>` tags (up to 2000 chars). Slow and may hit paywalls/bot detection.

3. **IV Rank unavailable:** True IV Rank requires 52-week historical ATM IV data, which yfinance doesn't provide. A future enhancement could persist daily IV to Azure Blob Storage.

4. **StockTwits rate limits:** The free API has undocumented rate limits. If rate-limited, sentiment returns an error dict and the pipeline continues without it.

5. **social_monitor.py kept for rollback:** The legacy Reddit/PRAW module is no longer imported but remains in the repo. Its env vars (REDDIT_*) are no longer required but won't cause errors if present.

---

## Git Info

- **Current branch:** `main`
- **Branches:** `main`, `feature/options-engine` (merged), `backup-pre-override`
- **Remote:** `origin` → `https://github.com/cdemchalk/daily_stock_analysis.git`
- **Latest commit on main:** `8d3a597` — "Add options strategy engine, Black-Scholes backtester, and enhanced pipeline"

---

## Deployment History

| Date | Commit | What Changed | CI/CD Status |
|------|--------|-------------|--------------|
| 2026-02-10 | `8d3a597` | Options engine, backtester, full pipeline overhaul | **Deployed successfully** (run #21863809717) |
| 2026-02-08 | `d6fab40` | CI/CD fix: DailyRunner/ in release zip | Deployed successfully |
| 2026-02-08 | `dd32448` | Azure Function deployment fix + report generation | Deployed successfully |

---

## Verification Results (2026-02-09)

- **COF single-ticker run:** CASH_SECURED_PUT recommended at 75% confidence
- **Backtest results:** 4 signals, 3 trades, 100% win rate, +3.6% avg return
- **Email delivery:** Confirmed working with strategy card + backtest card
- **BS pricing validation:** Put-call parity verified (diff=0.000000)
- **All Python files:** Pass AST syntax check

---

## Pending Work

1. **IV Rank from history:** Use `data/iv_history.csv` (now auto-populated daily) to compute 52-week IV Rank once sufficient data accumulates (~52 weeks of data needed).
2. **Multi-timeframe analysis:** Add weekly and monthly timeframe indicators.
3. **Sentiment source:** StockTwits API currently returning 403. Evaluate alternative sentiment sources (Reddit via official API, Finviz, or Twitter/X sentiment).
4. **Remove legacy deps:** Once StockTwits replacement is confirmed, remove `praw` and `nltk` from requirements.txt.
5. **Azure Blob persistence for IV history:** Currently local CSV (ephemeral on Azure /tmp); need Azure Blob Storage for persistent IV data.
6. **Multi-ticker verification:** Run `python main1.py BAC MSFT UVIX` to verify diverse ticker coverage (different sectors, high-IV ETFs).
7. **Monitor Monday email:** Verify the 2026-02-10 1PM UTC scheduled run delivers the new enhanced report format.

---

## How to Resume This Project

When returning to this project in a new Claude Code session:

1. **Navigate:** `cd /mnt/e/github/daily_stock_analysis`
2. **Read this file:** Claude Code auto-reads CLAUDE.md for project context
3. **Check deployment:** `gh run list --limit 3` to see recent CI/CD status
4. **Check Azure logs:** Use the App Insights queries in the Azure CLI section above
5. **Test locally:** `python main1.py COF --no-email` for a quick local test
6. **Pending work** is listed above — pick up from there

---

*Last reviewed: 2026-02-10 by Claude Code*
*Pipeline overhaul: 2026-02-08 — added options, sentiment, anchored VWAP, dashboard report, HTTP trigger, CLI*
*Options engine: 2026-02-09 — 7-strategy engine, BS backtesting, IV persistence, strategy cards in report*
*Production deployment: 2026-02-10 — merged feature/options-engine to main, CI/CD deployed to Azure*
