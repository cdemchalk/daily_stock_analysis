# Daily Stock Analysis Pipeline — Technical White Paper

**Author:** cdemchalk
**Version:** 2.0
**Date:** February 2026

---

## 1. Executive Summary

The Daily Stock Analysis Pipeline is a serverless, event-driven system that produces actionable investment intelligence for a watchlist of equity tickers. It runs on Azure Functions (Python 3.12), executes weekdays at 1:00 PM UTC, and delivers a dashboard-style HTML email report with:

- **22 technical indicators** per ticker (anchored VWAP, MACD, Bollinger Bands, RSI, SMA 50/200, support/resistance, 52-week range)
- **~22 fundamental data points** (P/E, growth, analyst targets, short interest, sector classification)
- **Options chain analysis** (ATM IV, premiums, put/call ratio, max pain, unusual activity, IV skew)
- **Market sentiment** via StockTwits (bullish/bearish ratio, sentiment score, community snippets)
- **AI-generated actionable summary** via GPT-5 (300-word structured output: Verdict, Buy & Hold Lens, Swing Setup, Options Play, Risk Flag)

The system supports three access modes: scheduled timer trigger (email), HTTP API (ad-hoc analysis), and CLI (local development). It introduces zero new pip dependencies beyond the existing requirements.txt.

**Target user:** A buy-and-hold investor who also trades rhythmic/swing patterns and wants actionable options trade ideas with specific strikes and premiums.

---

## 2. System Architecture

### 2.1 Component Overview

The system comprises 10 analysis modules orchestrated by `main1.py`, deployed as two Azure Functions (timer + HTTP trigger), with CI/CD via GitHub Actions.

| Component | Purpose | Lines of Code |
|-----------|---------|--------------|
| main1.py | Pipeline orchestrator | ~260 |
| technical.py | 22 technical indicators | ~185 |
| fundamentals.py | ~22 fundamental fields | ~100 |
| options_monitor.py | Options chain analysis + IV persistence | ~250 |
| options_strategy.py | 7-strategy engine with scoring | ~500 |
| backtester.py | Black-Scholes options backtester | ~290 |
| backtester_entry_exit.py | Entry/exit signal backtester | ~150 |
| market_sentiment.py | StockTwits sentiment | ~75 |
| news.py | Google News RSS + scraping | ~25 |
| strategy.py | Entry/exit signal evaluation | ~200 |
| summarizer.py | GPT-5 structured summarization | ~160 |
| report_builder.py | HTML dashboard + strategy cards | ~420 |
| emailer.py | Gmail SMTP delivery | ~25 |

### 2.2 Design Principles

1. **Fail-safe per module:** Each module is wrapped in try/except at the orchestrator level. If options data fails, the pipeline continues with `None` and the report gracefully omits the options bar.
2. **No new dependencies:** Options analysis uses yfinance's `.option_chain()`, sentiment uses `requests` (already in requirements.txt for news scraping). Zero additional packages.
3. **Backward-compatible signatures:** All modified function signatures use keyword arguments with defaults (`options=None`, `sentiment=None`), so existing callers work unchanged.
4. **Import-time safety:** New modules are imported with `try/except` fallbacks to `None`, so the timer trigger continues to work even if a new module has an import error.

### 2.3 Execution Order

The per-ticker execution order is deliberate:

1. **Fundamentals first** — provides `last_earnings_date` used by technical.py for anchored VWAP
2. **Technicals second** — provides `stock_price` used by options_monitor.py for ATM identification
3. **News, Strategy** — independent, no cross-dependencies
4. **Options** — needs stock price from technicals
5. **Sentiment** — independent (StockTwits API)
6. **Summarizer last** — needs all upstream data

---

## 3. Data Sources & Reliability

### 3.1 yfinance (v0.2.65)

| Aspect | Detail |
|--------|--------|
| Data provided | OHLCV price history, `.info` (182 fields), `.calendar`, `.earnings_dates`, `.options`, `.option_chain()`, `.splits` |
| Cost | Free (scrapes Yahoo Finance) |
| Rate limiting | Undocumented; aggressive concurrent requests may trigger 429s |
| Latency | 1-3 seconds per API call |
| Failure modes | Empty DataFrames on delisted/new tickers, MultiIndex column quirks, stale data on weekends |
| Mitigation | 3-tier fallback fetching (`yf.download` → `Ticker.history` → `auto_adjust=False`), `_normalize_ohlcv()` for column normalization |
| Version pinning | `==0.2.65` — pinned due to frequent breaking changes in yfinance |

### 3.2 StockTwits API

| Aspect | Detail |
|--------|--------|
| Endpoint | `GET https://api.stocktwits.com/api/2/streams/symbol/{TICKER}.json` |
| Cost | Free, no API key required for basic access |
| Rate limiting | Undocumented; returns HTTP 429 when exceeded |
| Data | Up to 30 most recent messages with user-tagged sentiment (Bullish/Bearish/None) |
| Failure modes | Rate limiting (429), ticker not found (404), service outage |
| Mitigation | 10-second timeout, graceful fallback to `None` on any error |
| Signal quality | High — users self-tag sentiment, stock-specific community |

**Why StockTwits over Reddit/PRAW:**
- Reddit requires 3 API credentials (client ID, secret, user agent) and `praw` + `nltk` dependencies
- NLP sentiment analysis (VADER) on noisy Reddit text is unreliable
- StockTwits users self-tag posts as Bullish/Bearish — more accurate than automated sentiment
- Zero authentication required, zero new dependencies
- ~75 lines vs 235 lines in the legacy `social_monitor.py`

**Why StockTwits over X/Twitter:**
- X API Basic tier ($200/month) restricts cashtag search to higher pricing tiers
- StockTwits is purpose-built for stock discussion

### 3.3 Google News RSS

| Aspect | Detail |
|--------|--------|
| Endpoint | `https://news.google.com/rss/search?q={ticker}+stock` |
| Cost | Free |
| Data | Top 5 news items with titles and links |
| Article scraping | Follows links, extracts `<p>` tags, truncates to 2000 chars |
| Failure modes | Paywalled articles, bot detection, slow response |
| Token cost impact | Full article content sent to GPT-5 increases token usage |

### 3.4 OpenAI GPT-5

| Aspect | Detail |
|--------|--------|
| Model | `gpt-5` |
| Purpose | Generate structured 300-word analysis per ticker |
| Max tokens | 800 (output) |
| Temperature | 0.3 (consistent, precise output) |
| System prompt | Experienced derivatives trader persona with Buy & Hold + Swing lenses |
| Input format | Structured labeled sections (TECHNICALS, FUNDAMENTALS, OPTIONS, SENTIMENT, STRATEGY, NEWS) |
| Output format | Constrained: Verdict, Buy & Hold Lens, Swing Setup, Options Play, What Changed, Risk Flag |
| Cost per ticker | ~2,000-3,000 input tokens + ~400-600 output tokens |

---

## 4. Technical Analysis Engine

### 4.1 Data Fetching

The `_fetch_ohlcv()` function implements a 3-tier fallback strategy to handle yfinance's inconsistent behavior across different tickers and market conditions:

1. `yf.download(auto_adjust=True)` — fastest, usually works
2. `Ticker.history(auto_adjust=True)` — different code path, sometimes succeeds when download fails
3. `yf.download(auto_adjust=False)` — raw data without dividend/split adjustment

All results pass through `_normalize_ohlcv()` which flattens MultiIndex columns (e.g., `('Close', 'AAPL')` → `Close`) and normalizes column names to Title Case.

### 4.2 Indicator Definitions

**Trend Indicators:**
- **EMA(9), EMA(20):** Exponential moving averages for short-term trend direction
- **SMA(50):** Medium-term trend. Price above SMA50 = bullish trend
- **SMA(200):** Long-term trend. Price above SMA200 = secular bull market. Requires 1-year data window

**Momentum Indicators:**
- **RSI(14):** Relative Strength Index. <30 = oversold, >70 = overbought. Computed using Wilder's smoothing (rolling mean of gains/losses)
- **MACD:** EMA(12) - EMA(26). Signal line = EMA(9) of MACD. Histogram = MACD - Signal. Positive histogram = bullish momentum

**Volatility Indicators:**
- **Bollinger Bands:** Upper = SMA(20) + 2σ, Lower = SMA(20) - 2σ
- **BB Width:** (Upper - Lower) / SMA(20). Width < 0.04 indicates a Bollinger squeeze (low volatility preceding a breakout)

**Volume Indicators:**
- **Volume Ratio:** Today's volume / 20-day average volume. >2.0 indicates unusual activity
- **Anchored VWAP:** Volume-weighted average price from last earnings date. Uses typical price `(H+L+C)/3`. Falls back to 20-day rolling VWAP if earnings date unavailable

**Price Structure:**
- **Support (20d):** 20-day rolling low — nearest demand zone
- **Resistance (20d):** 20-day rolling high — nearest supply zone
- **52-Week High/Low:** Full range context
- **% Changes:** 1-day, 5-day, 1-month (21 trading days), 3-month (63 trading days)

### 4.3 VWAP Fix

The original implementation computed VWAP cumulatively over 6 months:
```python
# BROKEN: cumulative VWAP diverges from price over time
data["VWAP"] = (data["Close"]*data["Volume"]).cumsum() / data["Volume"].cumsum()
```

This produced nonsense values (e.g., MSFT VWAP=$485 when price was $401). The fix uses **anchored VWAP**:

1. **Primary:** Anchor from last earnings date (provided by fundamentals.py). VWAP resets each earnings cycle, staying relevant to current price action
2. **Fallback:** 20-day rolling VWAP using rolling sums instead of cumulative sums

---

## 5. Options Analysis Engine

### 5.1 Expiry Selection

Target: nearest monthly expiry with 15-50 DTE (days to expiration). Preference for ~30 DTE to capture meaningful time value while avoiding near-expiry theta decay. Fallback to first expiry >7 DTE.

### 5.2 ATM Identification

ATM (at-the-money) strike is the strike closest to the current stock price. Both call and put at this strike are used for IV and premium calculations.

### 5.3 Implied Volatility

ATM IV is computed as the average of the ATM call IV and ATM put IV from yfinance's `.option_chain()` data. This represents the market's expectation of future volatility.

**IV Rank limitation:** True IV Rank requires comparing current ATM IV to the 52-week range of historical ATM IV. yfinance doesn't provide historical IV data, so IV Rank is not computed. The module returns a note about this limitation. A future enhancement could persist daily IV readings to Azure Blob Storage.

### 5.4 Max Pain Algorithm

Max pain identifies the strike price at which the total value of all in-the-money options is minimized. For each candidate strike:

```
call_pain = Σ max(0, test_strike - call_strike) × call_OI
put_pain  = Σ max(0, put_strike - test_strike) × put_OI
total     = call_pain + put_pain
```

The strike with the minimum total is max pain. Market makers theoretically benefit when price settles at max pain at expiration.

### 5.5 Unusual Activity Detection

Flags strikes where `volume > 2× openInterest`. This indicates new positions being opened (not just existing positions being traded), which can signal informed directional bets. Returns top 5 by volume.

### 5.6 IV Skew

Skew = OTM put IV (5% below stock price) - OTM call IV (5% above stock price). Positive skew indicates demand for downside protection. Negative skew indicates speculative call buying.

### 5.7 Daily IV Persistence

Each run appends ATM IV, premiums, and stock price to `data/iv_history.csv`. This builds a historical dataset for future IV Rank computation (requires ~252 data points = 1 year of daily snapshots). On Azure (read-only filesystem), writes to `/tmp/iv_history.csv` (ephemeral).

### 5.8 Options Strategy Engine (options_strategy.py)

The strategy engine algorithmically evaluates 7 defined-risk options strategies against current market conditions:

| # | Strategy | Market View | Key Conditions |
|---|----------|-------------|----------------|
| 1 | Covered Call | Neutral-bullish income | Price > SMA50, IV 25-45%, RSI 40-60 |
| 2 | Cash-Secured Put | Bullish on dip | Price near support, IV > 30%, RSI < 40 |
| 3 | Bull Call Spread | Directional up | EMA9 > EMA20, Price > VWAP, IV 20-50% |
| 4 | Bear Call Spread | Directional down | EMA9 < EMA20, RSI > 65, IV > 40% |
| 5 | Iron Condor | Range-bound | BB width < 0.06, IV 40-70%, RSI 40-60 |
| 6 | Protective Put | Long stock hedge | Price near resistance, earnings within DTE |
| 7 | Long Straddle | Big move expected | Earnings 5-15 days, unusual activity, IV < 50% |

**Scoring:** Each strategy has 5 weighted conditions. The weighted score (0-1) determines status:
- **Recommended** (score >= 0.60, >= 3 conditions met): Actionable trade setup
- **Monitor** (score >= 0.40): Conditions partially met, watch for improvement
- **Avoid**: Insufficient condition alignment

**Strike Selection:** Uses the full options chain DataFrames to find optimal strikes:
- ATM strikes via nearest-to-price selection
- OTM strikes via percentage-based targeting (e.g., 5% OTM for protective puts)
- Spread widths based on price-relative ranges (3-10% for bull call spreads)

**Risk Profiles:** Each recommendation includes computed max profit, max loss, breakeven, and risk/reward ratio based on actual chain premiums.

### 5.9 Black-Scholes Backtesting (backtester.py)

The backtester simulates historical options strategy performance using Black-Scholes pricing:

**Black-Scholes Implementation:**
```
d1 = [ln(S/K) + (r + σ²/2)T] / (σ√T)
d2 = d1 - σ√T
Call = S·N(d1) - K·e^(-rT)·N(d2)
Put  = K·e^(-rT)·N(-d2) - S·N(-d1)
```

Uses `numpy.erf` for the normal CDF — exact computation, no scipy required.

**Walk-Forward Process:**
1. Fetch 1-year OHLCV data
2. Compute all technical indicators per day
3. Check strategy entry conditions using same logic as live engine
4. On entry: price strategy legs using BS with historical volatility
5. Hold for target DTE or until exit signal
6. Compute P&L using BS repricing at exit
7. Aggregate: win rate, avg return, max drawdown, profit factor

**Accuracy Note:** BS pricing estimates are ~70-80% accurate vs real market premiums. Limitations include constant volatility assumption, no bid-ask spread modeling, and no early exercise for American options.

---

## 6. AI Summarization Pipeline

### 6.1 Prompt Engineering

The summarizer uses a two-message structure:

**System message:** Defines GPT as an experienced derivatives trader with two analysis lenses (Buy & Hold + Rhythmic/Swing). Constrains output to exactly 6 sections with a 300-word limit.

**User message:** Structured labeled sections generated by `_format_input()`:

```
TICKER: AAPL

TECHNICALS:
  price: 238.50
  RSI: 55.32
  VWAP: 235.80
  ...

FUNDAMENTALS:
  trailingPE: 31.2
  marketCap: 3650000000000
  ...

OPTIONS:
  expiry: 2026-03-20
  atm_iv: 0.2850
  ...

SENTIMENT:
  sentiment_score: 0.450
  bullish: 12, bearish: 3, total: 20

STRATEGY:
  entry_signal: False
  exit_signal: False

NEWS:
  - Apple Reports Record Q1 Revenue
  - ...
```

This structured input is far more token-efficient and parse-friendly than dumping raw Python dicts.

### 6.2 Constrained Output Format

```
**Verdict:** [one line]
**Buy & Hold Lens:** [2-3 bullets]
**Swing/Rhythmic Setup:** Entry: $X | Stop: $X | Target: $X
**Options Play:** [specific strategy with strike, expiry, premium]
**What Changed Today:** [1-2 bullets]
**Risk Flag:** [one line]
```

### 6.3 Token Economics

| Component | Est. Tokens |
|-----------|-------------|
| System prompt | ~200 |
| Technicals section | ~200-300 |
| Fundamentals section | ~150-200 |
| Options section | ~100-150 |
| Sentiment section | ~80-120 |
| Strategy section | ~50-80 |
| News titles (5) | ~100-150 |
| **Total input** | **~900-1,200** |
| **Output (300 words)** | **~400-600** |
| **Total per ticker** | **~1,300-1,800** |

Compared to the previous design which sent full article content (~2,000 chars × 5 articles = ~10,000 chars), the new design reduces input tokens by ~60% by sending only news titles.

---

## 7. Sentiment Analysis

### 7.1 StockTwits Signal Processing

StockTwits messages contain user-applied sentiment tags:
- **Bullish:** User explicitly marks their post as bullish
- **Bearish:** User explicitly marks as bearish
- **Untagged:** No sentiment tag applied

The sentiment score is computed as:
```
score = (bullish_count - bearish_count) / tagged_count
```

Scale: -1.0 (all bearish) to +1.0 (all bullish). Zero = evenly split.

### 7.2 Comparison: StockTwits vs Reddit vs X

| Metric | StockTwits | Reddit/PRAW | X/Twitter |
|--------|-----------|-------------|-----------|
| Cost | Free | Free (with API keys) | $200/mo+ |
| Auth required | None | 3 credentials | OAuth 2.0 |
| Sentiment method | User-tagged | NLP (VADER) | NLP required |
| Signal quality | High (self-tagged) | Low (noisy text) | Medium |
| Stock-specificity | Built-in ($AAPL) | Requires regex matching | Cashtag search restricted |
| Rate limiting | Undocumented | Documented | Strict |
| Dependencies | requests (existing) | praw, nltk | tweepy |
| Implementation | ~75 lines | ~235 lines | ~150 lines |

---

## 8. Report Generation

### 8.1 Dashboard Table

The report opens with a single-glance dashboard table:

| Column | Source | Styling |
|--------|--------|---------|
| Ticker | — | Bold |
| Price | technical.price | — |
| 1D% | technical.pct_change_1d | Signed format |
| Signal | strategy.entry/exit_signal | Color badges: green=BUY, red=EXIT, yellow=OVERBOUGHT, blue=OVERSOLD, gray=NEUTRAL |
| RSI | technical.RSI | Red if >70, green if <30 |
| ATM IV | options.atm_iv | Percentage format |
| Key Level | Nearest support or resistance | S: $X or R: $X |
| Sent. | sentiment.sentiment_score | Color-coded Bull/Bear/Mixed |
| Verdict | First line of GPT summary | Truncated to 60 chars |

### 8.2 Per-Ticker Detail Sections

Each ticker gets a detail card with:
- GPT summary (markdown converted to HTML)
- Options snapshot bar (expiry, DTE, ATM IV, call/put premiums, P/C ratio, max pain)
- Compact technicals line (SMA50, SMA200, VWAP, MACD histogram, BB width, volume ratio)
- Compact fundamentals line (market cap, P/E, recommendation, target price, short interest)

### 8.3 Catalyst Calendar

Aggregated table of upcoming earnings and ex-dividend dates across all tickers, sorted by proximity.

### 8.4 Email CSS Constraints

All styling uses inline CSS because email clients (Gmail, Outlook) strip `<style>` tags and `<link>` stylesheets. The report uses:
- `style` attributes on every element
- System font stack: `system-ui, Segoe UI, Roboto, Arial, sans-serif`
- Subtle color coding (Material Design palette)
- Max width 800px for readability

---

## 9. Azure Deployment Architecture

### 9.1 Functions v1 Programming Model

The project uses Azure Functions v1 programming model (function.json + \_\_init\_\_.py), not the newer v2 decorator model. Each function lives in its own directory:

- `DailyRunner/` — Timer trigger, fires Mon-Fri 1 PM UTC
- `StockAnalysisHttp/` — HTTP trigger, function-level auth

### 9.2 Timer vs HTTP Trigger

| Aspect | DailyRunner | StockAnalysisHttp |
|--------|------------|-------------------|
| Trigger | Timer (`0 0 13 * * 1-5`) | HTTP (GET/POST) |
| Auth | N/A (internal) | Function-level API key |
| Email | Yes (always sends) | No (returns report) |
| Tickers | From Key Vault | From request params |
| Output | None (side effect: email) | HTML or JSON response |

### 9.3 WEBSITE_RUN_FROM_PACKAGE

The function app runs with `WEBSITE_RUN_FROM_PACKAGE=1`, which mounts the deployment zip as a read-only filesystem at `/home/site/wwwroot`. This means:
- No server-side build (Oryx disabled)
- Faster cold starts (no pip install on startup)
- `/home/site/wwwroot` is read-only — any file writes must go to `/tmp`

### 9.4 Namespace Package Resolution

Azure Functions pre-installs `azure.functions` in the system Python. Our app needs `azure.identity` and `azure.keyvault` from `.python_packages/`. Without a namespace `__init__.py`, Python can't resolve both:

```python
# .python_packages/lib/site-packages/azure/__init__.py
from pkgutil import extend_path
__path__ = extend_path(__path__, __name__)
```

This allows both `azure.functions` (system) and `azure.identity` (vendored) to coexist.

---

## 10. CI/CD Pipeline

### 10.1 Workflow Structure

```
trigger: push to main OR manual dispatch
concurrency: deploy-azure-func (cancel in-progress)

Job 1: test
  - Validate requirements.txt (yfinance==0.2.65, peewee==3.18.2)
  - Install runtime deps
  - Install test deps
  - Run pytest (if tests exist)

Job 2: deploy (needs: test)
  - Prebuild .python_packages with 3 retries
  - Create azure namespace __init__.py
  - Verify vendored packages (yfinance, peewee)
  - Create release.zip (host.json, main1.py, modules/, DailyRunner/, StockAnalysisHttp/, requirements.txt, .python_packages/)
  - Verify zip contents (7 checks including both functions)
  - Azure login (OIDC credentials)
  - Set WEBSITE_RUN_FROM_PACKAGE=1
  - Disable Oryx build
  - Deploy via Azure/functions-action@v1
  - Post-deploy: verify 2 functions listed (DailyRunner + StockAnalysisHttp)
```

### 10.2 Zip Package Contents

The release.zip excludes `*.pyc`, `__pycache__/`, `.gitignore`, `.funcignore`, `*.md`, `*.log`. This keeps the package small and avoids deploying documentation to the function app.

---

## 11. Strategy Logic

### 11.1 Entry Signal

All three conditions must be true simultaneously:

1. **RSI < 35:** Stock is oversold. The 35 threshold (vs standard 30) captures early reversals
2. **Price < VWAP:** Stock is trading below volume-weighted fair value
3. **EMA9 crosses above EMA20:** Bullish short-term momentum crossover (previous bar: EMA9 < EMA20, current bar: EMA9 > EMA20)

### 11.2 Exit Signal

All three conditions must be true simultaneously:

1. **RSI > 65:** Stock is approaching overbought. The 65 threshold (vs standard 70) captures early exits
2. **Price > VWAP:** Stock is trading above volume-weighted fair value
3. **EMA9 crosses below EMA20:** Bearish momentum crossover

### 11.3 Additional Context

The strategy module also computes **ATR(14)** (Average True Range) for volatility context. ATR is used in the report but not in signal logic — it helps the GPT summarizer suggest appropriate stop-loss distances.

---

## 12. Security Model

### 12.1 API Key Management

| Secret | Storage | Access Method |
|--------|---------|--------------|
| OPENAI_API_KEY | Azure Key Vault | Function App Setting (KV reference) |
| EMAIL_USER | Azure App Settings | Environment variable |
| EMAIL_PASS | Azure App Settings | Environment variable |
| KEY_VAULT_NAME | Azure App Settings | Environment variable |
| Tickers | Azure Key Vault | SecretClient with DefaultAzureCredential |

### 12.2 Azure Key Vault Integration

The function app uses Managed Identity to authenticate to Key Vault via `DefaultAzureCredential`. No credentials are stored in code or environment variables for Key Vault access itself.

### 12.3 HTTP Trigger Auth

The HTTP trigger uses `authLevel: "function"`, requiring a function-specific API key passed as:
- Query parameter: `?code=<key>`
- Header: `x-functions-key: <key>`

This prevents unauthorized access while being simpler than Azure AD authentication.

### 12.4 Local Development

Local development uses `.env` file (excluded from git via `.gitignore`) with `python-dotenv`. The `loadenv.py` module detects the Azure runtime and skips `.env` loading when running in the function app.

---

## 13. Cost Analysis

### 13.1 Monthly Cost Estimate (3 tickers, weekday runs)

| Service | Unit Cost | Usage | Monthly Cost |
|---------|-----------|-------|-------------|
| Azure Functions | Free tier: 1M executions/mo | ~22 runs/mo × 1 execution | $0.00 |
| Azure Key Vault | $0.03/10K operations | ~66 operations/mo | $0.00 |
| Azure Storage | $0.0184/GB/mo | <1 MB | $0.00 |
| App Insights | Free tier: 5 GB/mo | <100 MB | $0.00 |
| OpenAI GPT-5 | ~$0.01/1K tokens | ~5K tokens × 3 tickers × 22 days = 330K tokens | ~$3.30 |
| yfinance | Free | — | $0.00 |
| StockTwits | Free | — | $0.00 |
| Google News | Free | — | $0.00 |
| **Total** | | | **~$3.30/mo** |

The system is extremely cost-efficient. OpenAI API usage is the only recurring cost.

---

## 14. Known Limitations & Future Roadmap

### 14.1 Current Limitations

1. **IV Rank requires data accumulation:** Daily IV snapshots are now persisted to `data/iv_history.csv`, but 52-week IV Rank requires ~252 data points. IV Rank will become available after ~1 year of daily runs
2. **Single timeframe:** All analysis uses daily bars. No weekly/monthly timeframe confirmation
3. **BS backtesting approximations:** Black-Scholes assumes constant volatility, European exercise, and no bid-ask spread. Real premiums may differ by 20-30%
4. **News latency:** Google News RSS may lag real-time breaking news by 15-60 minutes
5. **StockTwits API 403:** Sentiment source currently non-functional. Deferred to future session
6. **Options strategy engine uses snapshot data:** Strategy recommendations use current chain data, not intraday updates

### 14.2 Completed Enhancements

| Enhancement | Completed | Description |
|-------------|-----------|-------------|
| Options strategy engine | 2026-02-09 | 7 defined-risk strategies with weighted scoring and risk profiles |
| Black-Scholes backtesting | 2026-02-09 | Walk-forward BS-simulated backtesting for all 7 strategies |
| Entry/exit signal backtesting | 2026-02-09 | Historical validation of RSI/VWAP/EMA crossover signals |
| Daily IV persistence | 2026-02-09 | Auto-appends ATM IV to `data/iv_history.csv` each run |
| Strategy cards in report | 2026-02-09 | Color-coded strategy recommendation cards with risk profiles |
| GPT strategy integration | 2026-02-09 | GPT uses pre-computed strategy rec instead of improvising |

### 14.3 Future Roadmap

| Enhancement | Priority | Complexity | Benefit |
|-------------|----------|-----------|---------|
| IV Rank computation (once data accumulates) | High | Low | Contextualize current IV against historical range |
| Alternative sentiment source | High | Medium | Replace non-functional StockTwits API |
| Multi-timeframe analysis (weekly/monthly) | Medium | Low | Confirm daily signals with higher timeframe trends |
| Azure Blob IV persistence | Medium | Medium | Durable IV history across deployments |
| Bollinger squeeze alert | Low | Low | Flag imminent breakout setups |
| Mobile push notifications | Low | Medium | Faster alert delivery than email |
| Remove legacy praw/nltk deps | Low | Low | Reduce package size and deploy time |

---

*Document generated: February 2026*
*Pipeline version: 3.0 (options strategy engine + backtesting)*
