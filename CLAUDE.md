# daily_stock_analysis — Claude Reference

## Project Overview

**Author:** cdemchalk
**Created:** August 2025
**Repo:** `/mnt/e/github/daily_stock_analysis` (git, branches: `main`, `backup-pre-override`)
**Purpose:** Automated daily stock analysis pipeline deployed on Azure Functions. Runs weekdays at 1:00 PM UTC, analyzing a configurable watchlist of tickers and emailing a styled HTML report with technical, fundamental, social, and AI-generated insights.
**Status:** Fully operational on Azure as of 2026-02-07 (manually verified via CLI trigger).

---

## Architecture

```
daily_stock_analysis/
├── main1.py                        # Orchestrator: loads env, fetches data, builds report, sends email
├── DailyRunner/
│   ├── __init__.py                 # Azure Function entry point (timer trigger), imports main1.run()
│   └── function.json               # Timer trigger config (Mon-Fri 1 PM UTC)
├── modules/
│   ├── __init__.py                 # Empty package init
│   ├── loadenv.py                  # Smart env loader: skips .env on Azure, uses dotenv locally
│   ├── technical.py                # Technical indicators (EMA9, EMA20, RSI, VWAP) via yfinance (3-tier fallback)
│   ├── fundamentals.py             # Fundamental data (earnings, dividends, splits) via yfinance
│   ├── news.py                     # Google News RSS + full article scraping (truncated to 2000 chars)
│   ├── strategy.py                 # Entry/exit signal evaluator (RSI, VWAP, EMA crossovers, ATR)
│   ├── social_monitor.py           # Reddit (PRAW) social sentiment, velocity, keyword flags
│   ├── summarizer.py               # OpenAI GPT-5 summarization (500-800 word investor brief)
│   ├── report_builder.py           # HTML report generator with badges, formatted sections
│   ├── emailer.py                  # Gmail SMTP sender (SSL, port 465)
│   └── YF.py                       # Standalone yfinance diagnostic script
├── data/
│   └── social_baseline.json        # Rolling 30-day social velocity baseline per ticker
├── .env                            # Local environment secrets
├── .gitignore                      # Excludes .env, __pycache__, .python_packages/, etc.
├── .funcignore                     # Azure deploy exclusions (*.md, claude-docs/, .git/, etc.)
├── .github/workflows/
│   └── deploy-azure-func.yaml      # GitHub Actions CI/CD: test + deploy to Azure Functions
├── host.json                       # Azure Functions v2 host config (extension bundle v4.x)
├── requirements.txt                # Python 3.12 dependencies (pinned versions)
├── README.md                       # Stub readme
└── stock-daily-runner.PublishSettings  # Azure publish profile
```

---

## Pipeline Flow

1. **Timer fires** — Azure Function `DailyRunner/__init__.py`, Mon-Fri 1 PM UTC
2. Calls `main1.run()`
3. **Watchlist loaded** from Azure Key Vault (in Azure) or `TICKERS` env var (locally)
   - Currently set to `COF` (Capital One) in `.env`
   - Key Vault ticker list: `BAC,MSFT,UVIX`
4. For each ticker:
   - `technical.get_technical_indicators()` — 6-month daily OHLCV, computes EMA9, EMA20, RSI, VWAP (3 fallback methods for yfinance quirks)
   - `fundamentals.get_fundamentals()` — earnings date, dividend date, splits
   - `news.fetch_news()` — top 5 Google News RSS items **with full article content scraped** (up to 2000 chars each)
   - `strategy.evaluate_strategy()` — entry/exit signals based on technical crossovers
   - `social_monitor.social_snapshot()` — Reddit mentions, VADER sentiment, velocity, keyword flags, snippets
   - `summarizer.summarize_insights()` — GPT-5 generates 500-800 word structured investor brief
5. `report_builder.build_html_report()` — assembles styled HTML with formatted summary sections, badges
6. `emailer.send_email()` — sends via Gmail SMTP to self
7. **Typical runtime:** ~190 seconds for 3 tickers

---

## Key Differences from /mnt/e/Financial/ (older copy)

| Feature | Financial/ (old) | daily_stock_analysis/ (current) |
|---------|-----------------|-------------------------------|
| .gitignore | Missing | Present |
| loadenv.py | Hardcoded path `/mnt/e/Financial/.env` | Auto-detects; skips .env on Azure |
| Watchlist | Hardcoded in code | Key Vault (Azure) or env var (local) |
| Key Vault | Referenced but unused | Integrated via `azure-identity` + `azure-keyvault-secrets` |
| News module | Titles only | Full article content scraped |
| Summarizer | 180 words | 500-800 words, structured sections |
| Social monitor | StockTwits active | StockTwits disabled (requires API key) |
| Logging | print() statements | Proper `logging` module throughout |
| requirements.txt | Had Python shebang | Clean, pinned versions, extra deps |
| CI/CD | Simple deploy | Full test + build + verify + deploy pipeline |
| Python version | 3.10 | 3.12 |
| Extension bundle | v3.x | v4.x |
| Ticker regex | Simple pattern | Expanded with company name matching (BAC/MSFT/UVIX) |
| Report builder | Basic | Formatted summary with `**bold**` section parsing |

---

## Azure Deployment

- **Runtime:** Azure Functions v2, Python 3.12
- **Schedule:** `0 0 13 * * 1-5` (every weekday at 1:00 PM UTC)
- **Resource Group:** `rg-stocks`
- **Key Vault:** `stockdailyvault20172025`
- **Auth:** `azure-identity` DefaultAzureCredential (Managed Identity on Azure)
- **CI/CD:** GitHub Actions on push to `main` or manual `workflow_dispatch`
  - **Test job:** validates requirements.txt, installs deps, runs pytest
  - **Deploy job:** prebuilds deps into `.python_packages/`, creates `release.zip`, deploys via `Azure/functions-action@v1`
  - **Deployment mode:** `WEBSITE_RUN_FROM_PACKAGE=1`, Oryx build disabled
  - **Secrets required:** `AZURE_CREDENTIALS`, `AZURE_FUNCTIONAPP_NAME`
- **Post-deploy:** sanity check lists deployed functions

### Manual Deploy from CLI

When deploying outside CI/CD (e.g., hotfixes), build and deploy a zip directly:

```bash
# Build .python_packages
pip install --target .python_packages/lib/site-packages -r requirements.txt

# Ensure azure namespace package init exists (critical for azure.identity to coexist with azure.functions)
echo 'from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)' > .python_packages/lib/site-packages/azure/__init__.py

# Create and deploy zip
cd /mnt/e/github/daily_stock_analysis
zip -r /tmp/release.zip host.json main1.py modules/ DailyRunner/ requirements.txt .python_packages/ -x "*.pyc" "__pycache__/*"
az functionapp deployment source config-zip --resource-group rg-stocks --name stock-daily-runner --src /tmp/release.zip

# Restart and verify
az functionapp restart --name stock-daily-runner --resource-group rg-stocks
az functionapp function list --name stock-daily-runner --resource-group rg-stocks --output table
```

### Manual Function Trigger

```bash
# Get master key
MASTER_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query masterKey -o tsv)

# Trigger via admin API
curl -s -X POST "https://stock-daily-runner.azurewebsites.net/admin/functions/DailyRunner" \
  -H "x-functions-key: $MASTER_KEY" \
  -H "Content-Type: application/json" \
  -d '{}'
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
| yfinance | ==0.2.65 | Stock market data (pinned) |
| pandas | >=2.2.2,<2.4.0 | Data manipulation (upper-bounded) |
| numpy | ==2.1.3 | Numerical operations (pinned) |
| requests | >=2.32.0 | HTTP (news scraping) |
| beautifulsoup4 | >=4.12.3 | HTML/RSS parsing |
| praw | >=7.7.1 | Reddit API client |
| nltk | >=3.9 | VADER sentiment analysis |
| peewee | ==3.18.2 | ORM (yfinance dependency, pinned) |
| lxml | >=4.9.1 | XML parser |
| html5lib | >=1.1 | HTML parser |
| platformdirs | >=2.0.0 | Platform-specific directories |
| pytz | >=2022.5 | Timezone support |
| frozendict | >=2.3.4 | Immutable dictionaries |
| multitasking | >=0.0.7 | yfinance threading support |

---

## Strategy Logic (strategy.py)

**Entry Signal** (all must be true):
- RSI < 35 (oversold)
- Price < VWAP (below volume-weighted average)
- EMA9 crosses above EMA20 (bullish crossover)

**Exit Signal** (all must be true):
- RSI > 65 (overbought)
- Price > VWAP (above volume-weighted average)
- EMA9 crosses below EMA20 (bearish crossover)

Also computes ATR(14) for volatility context. Uses robust 3-tier data fetching with MultiIndex column normalization.

---

## Social Monitoring (social_monitor.py)

**Reddit subreddits:** wallstreetbets, stocks, investing, options, pennystocks
**StockTwits:** Disabled (logged as warning)

**Ticker matching:** Expanded regex patterns for BAC (Bank of America), MSFT (Microsoft), UVIX (VIX ETF) including company names and common variations.

**Metrics:**
- Mentions per hour (velocity based on actual time span)
- Z-score vs 30-day rolling baseline
- VADER sentiment (avg, % positive > 0.05, % negative < -0.05)
- Keyword flags: pump, dump, moon, crash, short, buy, sell, hold, yolo, dd, lawsuit, offering, downgrade, bankruptcy
- Hype spike detection (z_mph >= 2.0)
- Bearish pressure detection (neg_share > 40% + negative keywords)
- Text snippets (first 200 chars of top 5 items) passed to summarizer

**Baseline storage:** `/tmp/social_baseline.json` (configurable via `SOCIAL_BASELINE_PATH` env var)

---

## Known Issues & Observations

1. **SECURITY — .env still in repo working tree:** `.gitignore` excludes `.env`, but verify it was never committed to git history. Contains plaintext API keys for OpenAI, Gmail, Reddit, and Key Vault.

3. **social_baseline.json in /tmp is ephemeral:** On Azure, `/tmp` is cleared on function restarts. Baseline history (30-day rolling averages) will be lost. Consider Azure Blob Storage or Table Storage for persistence.

4. **Watchlist env var inconsistency:** `.env` has `TICKERS=COF` (single ticker), but `social_monitor.py` has hardcoded regex patterns only for BAC, MSFT, and UVIX. COF will fall through to the generic regex pattern.

5. **News module scrapes full articles:** `news.py` follows each news link and scrapes all `<p>` tags (up to 2000 chars). This is slow and may hit paywalls/bot detection. Each ticker's news adds significant latency and token cost to the GPT-5 call.

6. **Reddit client reconnects per ticker:** `_reddit_client()` is called fresh for each `fetch_reddit_activity()` call, creating a new PRAW client and doing a test fetch each time. With 3+ tickers this is redundant.

7. **reddit_healthcheck logs partial secrets:** Line 231 of `social_monitor.py` logs the first 4 chars of `REDDIT_CLIENT_ID` and `REDDIT_CLIENT_SECRET`. While truncated, this still leaks partial credential info to Azure App Insights.

8. **loadenv clears env vars before reload:** Lines 35-37 of `loadenv.py` pop matching keys from `os.environ` before loading .env. In Azure (where env vars come from App Settings), this code path is skipped, but locally it forces a fresh load with `override=True`.

9. **Azure namespace package init required on deploy:** When building `.python_packages/`, an `azure/__init__.py` with `extend_path` must exist so that `azure.identity` and `azure.keyvault` (in .python_packages) can coexist with `azure.functions` (system-installed). Without this, `ModuleNotFoundError: No module named 'azure.identity'` occurs. The CI/CD pipeline now handles this automatically after `pip install --target`.

---

## Bugs Fixed (2026-02-07 Session)

### 1. DailyRunner/function.json — PowerShell instead of JSON
**Symptom:** `az functionapp function list` returned `[]`. Function never ran.
**Root cause:** `function.json` contained a PowerShell script (`$json = @"..."@; Move-Item`) instead of valid JSON.
**Fix:** Replaced with proper timer trigger JSON:
```json
{
  "scriptFile": "__init__.py",
  "bindings": [{
    "name": "mytimer",
    "type": "timerTrigger",
    "direction": "in",
    "schedule": "0 0 13 * * 1-5"
  }]
}
```

### 2. report_builder.py — NoneType crash on failed tickers
**Symptom:** Email contained only "Error generating report" with no data.
**Root cause:** When a ticker's data fetch fails, `main1.py` stores `"strategy": None`. Python's `dict.get("strategy", {})` returns `None` (not `{}`) when the key exists with value `None`. Calling `.get()` on `None` then raised `AttributeError`.
**Fix:** Changed lines 30-33 from `p.get("strategy", {})` to `p.get("strategy") or {}` (same for `social`, `technical`, `summary`).

### 3. SOCIAL_BASELINE_PATH — Read-only filesystem
**Symptom:** `[Errno 30] Read-only file system: '/home/site/wwwroot/social_baseline.json'`
**Root cause:** `WEBSITE_RUN_FROM_PACKAGE=1` mounts wwwroot as read-only from the deploy zip. The `SOCIAL_BASELINE_PATH` app setting pointed to wwwroot.
**Fix:** Updated Azure app setting: `SOCIAL_BASELINE_PATH=/tmp/social_baseline.json`

### 4. Azure namespace package conflict
**Symptom:** `ModuleNotFoundError: No module named 'azure.identity'`
**Root cause:** `azure.functions` is system-installed by the Azure host, while `azure.identity` / `azure.keyvault` are in `.python_packages/`. Without a namespace `__init__.py`, Python can't find both.
**Fix:** Created `.python_packages/lib/site-packages/azure/__init__.py`:
```python
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

### 5. .gitignore cleanup
**Before:** Had duplicate `.env` entries including a quoted `".env"`, missing useful exclusions.
**After:** Clean list: `.env`, `__pycache__/`, `*.pyc`, `*.pyo`, `*.pyd`, `.vscode/`, `.ipynb_checkpoints/`, `*.log`, `.python_packages/`

### 6. .funcignore updated
**Added:** `*.md`, `CLAUDE.md`, `claude-docs/`, `*.log`, `.gitignore` — prevents documentation from being included in Azure deploy packages.

---

## Environment Variables

| Variable | Purpose | Where Set |
|----------|---------|-----------|
| OPENAI_API_KEY | GPT-5 summarization | .env / Azure App Settings / Key Vault |
| EMAIL_USER | Gmail sender address | .env / Azure App Settings |
| EMAIL_PASS | Gmail App Password | .env / Azure App Settings |
| REDDIT_CLIENT_ID | Reddit API auth | .env / Azure App Settings |
| REDDIT_CLIENT_SECRET | Reddit API auth | .env / Azure App Settings |
| REDDIT_USER_AGENT | Reddit API identifier | .env / Azure App Settings |
| KEY_VAULT_NAME | Azure Key Vault name (`stockdailyvault20172025`) | .env / Azure App Settings |
| TICKERS | Comma-separated ticker list | .env / Key Vault (secret: "Tickers") |
| SOCIAL_BASELINE_PATH | Path to baseline JSON (`/tmp/social_baseline.json`) | Azure App Settings |
| FUNCTIONS_WORKER_RUNTIME | Set to `python` by Azure (used to detect Azure environment) | Azure runtime |
| WEBSITE_RUN_FROM_PACKAGE | Set to `1` by CI/CD for zip deployment | Azure App Settings |

---

## Azure CLI Access (for Claude Code)

Azure CLI is installed natively in WSL at `/usr/bin/az` (v2.83.0).
Authenticated as `cdemchalk@yahoo.com` on subscription `Azure subscription 1`.

### Useful Commands

```bash
# Function app status
az functionapp show --name stock-daily-runner --resource-group rg-stocks --output table

# List deployed functions
az functionapp function list --name stock-daily-runner --resource-group rg-stocks --output table

# View app settings
az webapp config appsettings list --name stock-daily-runner --resource-group rg-stocks --output table

# Stream live logs
az functionapp log tail --name stock-daily-runner --resource-group rg-stocks

# Query App Insights traces (last 7 days)
az monitor app-insights query --app 45c7a0c4-413d-4c56-af04-0fec9664d66c --analytics-query "traces | where timestamp > ago(7d) | order by timestamp desc | take 30 | project timestamp, message, severityLevel"

# Query App Insights exceptions
az monitor app-insights query --app 45c7a0c4-413d-4c56-af04-0fec9664d66c --analytics-query "exceptions | where timestamp > ago(7d) | order by timestamp desc | take 20 | project timestamp, type, outerMessage"

# Trigger function manually (use master key + curl, az invoke doesn't work reliably)
MASTER_KEY=$(az functionapp keys list --name stock-daily-runner --resource-group rg-stocks --query masterKey -o tsv)
curl -s -X POST "https://stock-daily-runner.azurewebsites.net/admin/functions/DailyRunner" \
  -H "x-functions-key: $MASTER_KEY" -H "Content-Type: application/json" -d '{}'

# Restart function app
az functionapp restart --name stock-daily-runner --resource-group rg-stocks

# Update app settings
az webapp config appsettings set --name stock-daily-runner --resource-group rg-stocks --settings KEY=VALUE
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

## Git Info

- **Current branch:** `main`
- **Branches:** `main`, `backup-pre-override`
- **Remote:** `origin` (GitHub)
- **Uncommitted local changes:** function.json fix, report_builder.py fix, .gitignore cleanup, .funcignore update, CLAUDE.md updates

---

## Pending Work

1. **Verify CI/CD deploy succeeds:** The yaml now includes `DailyRunner/` in the zip and creates the azure namespace `__init__.py`. Monitor the next GitHub Actions run to confirm it deploys correctly.

---

*Last reviewed: 2026-02-07 by Claude Code*
*Azure CLI integrated: 2026-02-07*
*Function verified operational: 2026-02-07 (3 tickers: BAC, MSFT, UVIX — email sent successfully)*
