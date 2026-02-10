# Daily Stock Analysis — System Architecture

## System-Level View

```mermaid
graph TB
    subgraph "User Touchpoints"
        EMAIL[📧 Email Report]
        HTTP[🌐 HTTP API]
        CLI[💻 CLI]
    end

    subgraph "Azure Functions Runtime"
        TIMER[DailyRunner<br/>Timer Trigger<br/>Mon-Fri 1PM UTC]
        HTTPFN[StockAnalysisHttp<br/>HTTP Trigger<br/>Function Auth]
        MAIN[main1.py<br/>Orchestrator]
    end

    subgraph "Analysis Modules"
        FUND[fundamentals.py]
        TECH[technical.py]
        NEWS[news.py]
        STRAT[strategy.py]
        OPTS[options_monitor.py]
        OSTRAT[options_strategy.py]
        BT[backtester.py]
        BTEE[backtester_entry_exit.py]
        SENT[market_sentiment.py]
        SUM[summarizer.py]
        RPT[report_builder.py]
    end

    subgraph "External Data Sources"
        YF[yfinance API<br/>Price, Options, Fundamentals]
        GNEWS[Google News RSS]
        STWITS[StockTwits API]
        OPENAI[OpenAI GPT-5]
    end

    subgraph "Azure Infrastructure"
        KV[Key Vault<br/>stockdailyvault20172025]
        AI[App Insights<br/>Monitoring]
        STORAGE[Storage Account<br/>dailystockstorage]
    end

    subgraph "CI/CD"
        GH[GitHub Actions<br/>deploy-azure-func.yaml]
    end

    TIMER --> MAIN
    HTTPFN --> MAIN
    CLI --> MAIN

    MAIN --> FUND
    MAIN --> TECH
    MAIN --> NEWS
    MAIN --> STRAT
    MAIN --> OPTS
    OPTS --> OSTRAT
    OSTRAT --> BT
    MAIN --> BTEE
    MAIN --> SENT
    MAIN --> SUM
    MAIN --> RPT

    FUND --> YF
    TECH --> YF
    OPTS --> YF
    NEWS --> GNEWS
    SENT --> STWITS
    SUM --> OPENAI

    MAIN --> KV
    MAIN --> AI
    RPT --> EMAIL
    HTTPFN --> HTTP
    GH --> STORAGE
```

### ASCII Fallback — System Level

```
┌─────────────────────────────────────────────────────────────────────┐
│                        USER TOUCHPOINTS                             │
│   📧 Email (Timer)    🌐 HTTP API (Ad-hoc)    💻 CLI (Local)       │
└──────────┬──────────────────┬─────────────────────┬─────────────────┘
           │                  │                     │
           ▼                  ▼                     ▼
┌──────────────────────────────────────────────────────────────────────┐
│                    AZURE FUNCTIONS RUNTIME                            │
│                                                                      │
│  ┌──────────────┐  ┌──────────────────┐  ┌────────────────────────┐  │
│  │ DailyRunner  │  │ StockAnalysisHttp│  │ main1.py               │  │
│  │ Timer Trigger│──│ HTTP Trigger     │──│ Orchestrator           │  │
│  │ M-F 1PM UTC  │  │ Function Auth    │  │ run(tickers, email,fmt)│  │
│  └──────────────┘  └──────────────────┘  └──────────┬─────────────┘  │
└─────────────────────────────────────────────────────┼────────────────┘
                                                      │
                    ┌─────────────────────────────────┼──────────────┐
                    │         ANALYSIS PIPELINE        │              │
                    │                                  ▼              │
                    │  1. fundamentals.py ──── yfinance .info         │
                    │  2. technical.py ─────── yfinance OHLCV (1yr)   │
                    │  3. news.py ──────────── Google News RSS        │
                    │  4. strategy.py ──────── yfinance OHLCV (6mo)   │
                    │  5. options_monitor.py ── yfinance .option_chain │
                    │  5b.options_strategy.py ─ 7-strategy engine     │
                    │  5c.backtester.py ─────── BS backtest (opt.)    │
                    │     backtester_entry_exit  signal backtest       │
                    │  6. market_sentiment.py ─ StockTwits API        │
                    │  7. summarizer.py ─────── OpenAI GPT-5          │
                    │  8. report_builder.py ── HTML generation        │
                    └─────────────────────────────────────────────────┘
                                                      │
           ┌──────────────────────────────────────────┼──────────────┐
           │              AZURE INFRASTRUCTURE         │              │
           │  ┌────────────┐ ┌─────────────┐ ┌───────┴──────────┐   │
           │  │ Key Vault  │ │ App Insights│ │ Storage Account  │   │
           │  │ Tickers    │ │ Logs/Errors │ │ ZIP Deploy Pkgs  │   │
           │  └────────────┘ └─────────────┘ └──────────────────┘   │
           └────────────────────────────────────────────────────────┘
```

---

## Pipeline-Level View

```mermaid
sequenceDiagram
    participant T as Trigger
    participant M as main1.py
    participant F as fundamentals
    participant TA as technical
    participant N as news
    participant S as strategy
    participant O as options_monitor
    participant SE as market_sentiment
    participant AI as summarizer (GPT-5)
    participant R as report_builder
    participant E as emailer

    T->>M: run(tickers, email_flag, format)

    loop For each ticker
        M->>F: get_fundamentals(ticker)
        F-->>M: fa (22 fields + last_earnings_date)

        M->>TA: get_technical_indicators(ticker, last_earnings_date)
        TA-->>M: ta (22 indicators)

        M->>N: fetch_news(ticker)
        N-->>M: news_items (up to 5)

        M->>S: evaluate_strategy(ticker)
        S-->>M: strat (entry/exit signals)

        M->>O: get_options_data(ticker, stock_price, return_chain=True)
        O-->>M: options (20 metrics + chain DFs)

        Note over M: Options Strategy Engine
        M->>M: recommend_strategies(options, ta, fa, calls_df, puts_df)
        Note over M: Returns ranked list of 7 strategies with risk profiles

        opt --backtest flag
            M->>M: backtest_strategy(ticker, top_strategy)
            M->>M: backtest_entry_exit(ticker)
        end

        M->>SE: get_market_sentiment(ticker)
        SE-->>M: sentiment (score, ratios, snippets)

        M->>AI: summarize_insights(ticker, ta, fa, news, options, sentiment, strategy, options_strategies)
        AI-->>M: 300-word structured summary (uses pre-computed strategy)
    end

    M->>R: build_html_report(summaries, timestamp)
    R-->>M: HTML (dashboard + detail + calendar)

    alt send_email_flag = True
        M->>E: send_email(html)
    end

    M-->>T: HTML or JSON response
```

---

## Module-Level View

### technical.py — Internal Structure

```mermaid
graph LR
    subgraph "Data Fetching"
        A[_fetch_ohlcv] --> B[yf.download]
        A --> C[Ticker.history]
        A --> D[yf.download auto_adjust=False]
        B --> E[_normalize_ohlcv]
        C --> E
        D --> E
    end

    subgraph "Indicator Computation"
        E --> F[EMA 9, 12, 20, 26]
        E --> G[_compute_rsi]
        E --> H[MACD = EMA12 - EMA26]
        E --> I[Bollinger Bands]
        E --> J[SMA 50, 200]
        E --> K[Volume Ratio]
        E --> L[Support/Resistance 20d]
        E --> M[52-week High/Low]
        E --> N[% Changes 1d/5d/1mo/3mo]
        E --> O[_compute_anchored_vwap]
    end

    subgraph "Output"
        F & G & H & I & J & K & L & M & N & O --> P[22-key dict]
    end
```

### options_monitor.py — Internal Structure

```mermaid
graph TD
    A[get_options_data] --> B[stock.options — get expiry dates]
    B --> C[Find nearest monthly expiry 15-50 DTE]
    C --> D[stock.option_chain — fetch calls/puts]
    D --> E[ATM strike identification]
    E --> F[ATM IV — avg call+put IV]
    E --> G[ATM premiums + % of stock]
    D --> H[P/C Ratio — volume and OI]
    D --> I[_compute_max_pain]
    D --> J[_find_unusual_activity — vol > 2x OI]
    D --> K[_compute_skew — OTM put IV - call IV]
    F & G & H & I & J & K --> L[20-key result dict]
```

---

## Deployment View

```mermaid
graph TD
    subgraph "GitHub Actions CI/CD"
        A[Push to main] --> B[Test Job]
        B --> B1[Validate requirements.txt]
        B --> B2[Install deps]
        B --> B3[Run pytest]
        B1 & B2 & B3 --> C[Deploy Job]
        C --> C1[Prebuild .python_packages]
        C1 --> C2[Create azure namespace __init__.py]
        C2 --> C3[Verify yfinance + peewee]
        C3 --> C4[Create release.zip]
        C4 --> C5[Verify zip contents]
    end

    subgraph "Azure Deploy"
        C5 --> D1[Azure Login OIDC]
        D1 --> D2[Set WEBSITE_RUN_FROM_PACKAGE=1]
        D2 --> D3[Disable Oryx Build]
        D3 --> D4[Deploy via functions-action]
        D4 --> D5[Post-deploy sanity check]
        D5 --> D6[Verify 2 functions listed]
    end

    subgraph "release.zip Contents"
        Z1[host.json]
        Z2[main1.py]
        Z3[modules/]
        Z4[DailyRunner/]
        Z5[StockAnalysisHttp/]
        Z6[requirements.txt]
        Z7[.python_packages/]
    end
```

### ASCII Fallback — Deployment

```
GitHub Push to main
        │
        ▼
┌──────────────────────────────┐
│       TEST JOB               │
│  1. Validate requirements.txt│
│  2. Install deps             │
│  3. Run pytest               │
└──────────────┬───────────────┘
               │ (pass)
               ▼
┌──────────────────────────────┐
│       DEPLOY JOB             │
│  1. Prebuild .python_packages│
│  2. Create azure __init__.py │
│  3. Verify packages          │
│  4. Create release.zip       │
│     ├── host.json            │
│     ├── main1.py             │
│     ├── modules/             │
│     ├── DailyRunner/         │
│     ├── StockAnalysisHttp/   │
│     ├── requirements.txt     │
│     └── .python_packages/    │
│  5. Verify zip contents      │
│  6. Azure login (OIDC)       │
│  7. Set run-from-package     │
│  8. Disable Oryx             │
│  9. Deploy                   │
│ 10. Sanity check (2 funcs)   │
└──────────────────────────────┘
```

---

## Data Flow View

```mermaid
graph LR
    subgraph "Data Sources"
        YF[yfinance<br/>Free, rate-limited]
        GN[Google News RSS<br/>Free, 5 items/ticker]
        ST[StockTwits API<br/>Free, no auth]
        OAI[OpenAI GPT-5<br/>Pay per token]
    end

    subgraph "Data Consumers"
        FUND[fundamentals.py<br/>stock.info + calendar + earnings_dates]
        TECH[technical.py<br/>1yr daily OHLCV]
        STRAT[strategy.py<br/>6mo daily OHLCV]
        OPTS[options_monitor.py<br/>stock.options + option_chain]
        NEWS[news.py<br/>RSS + article scrape]
        SENT[market_sentiment.py<br/>30 messages per ticker]
        SUM[summarizer.py<br/>Structured prompt → 300 words]
    end

    YF --> FUND
    YF --> TECH
    YF --> STRAT
    YF --> OPTS
    GN --> NEWS
    ST --> SENT
    OAI --> SUM

    subgraph "Output Formats"
        HTML[HTML Dashboard Email]
        JSON[JSON API Response]
        TERM[Terminal Output]
    end

    SUM --> HTML
    SUM --> JSON
    SUM --> TERM
```

### ASCII Fallback — Data Flow

```
DATA SOURCES                  MODULES                      OUTPUTS
────────────                  ───────                      ───────

yfinance ─────┬── fundamentals.py (stock.info)
              ├── technical.py (1yr OHLCV)         ┌── 📧 HTML Email
              ├── strategy.py (6mo OHLCV)    ──────┤── 🌐 JSON API
              └── options_monitor.py (chains)       └── 💻 Terminal
                                               ▲
Google News ──── news.py (RSS + scrape)        │
                                               │
StockTwits ───── market_sentiment.py ──────────┤
                                               │
OpenAI GPT-5 ── summarizer.py ────────────────┘
```

---

## Technical Indicators Computed

| Module | Indicator | Method |
|--------|-----------|--------|
| technical.py | EMA 9, EMA 20 | Exponential moving average |
| technical.py | RSI (14) | Wilder RSI via rolling gain/loss |
| technical.py | MACD line | EMA(12) - EMA(26) |
| technical.py | MACD signal | EMA(9) of MACD line |
| technical.py | MACD histogram | MACD line - signal |
| technical.py | Bollinger upper | SMA(20) + 2*StdDev(20) |
| technical.py | Bollinger lower | SMA(20) - 2*StdDev(20) |
| technical.py | BB width | (upper - lower) / SMA(20) |
| technical.py | SMA 50, SMA 200 | Simple moving average |
| technical.py | Anchored VWAP | From last earnings or 20-day rolling |
| technical.py | Volume ratio | Today vol / 20-day avg vol |
| technical.py | Support (20d) | 20-day rolling low |
| technical.py | Resistance (20d) | 20-day rolling high |
| technical.py | 52-week high/low | Max/min over 1 year |
| technical.py | % changes | 1d, 5d, 1mo, 3mo |
| strategy.py | ATR (14) | Average true range |
| options_monitor.py | ATM IV | Avg of ATM call + put IV |
| options_monitor.py | Max pain | Strike minimizing total ITM value |
| options_monitor.py | IV skew | OTM put IV - OTM call IV (5% OTM) |
| options_monitor.py | P/C ratio | Volume and open interest ratios |

---

## Options Strategy Engine

### options_strategy.py — Internal Structure

```mermaid
graph TD
    A[recommend_strategies] --> B[For each of 7 strategies]
    B --> C[_evaluate_conditions<br/>Check technical + options + fundamental conditions]
    C --> D[_score_conditions<br/>Weighted scoring 0-1]
    D --> E{score >= 0.60?}
    E -- Yes --> F[recommended]
    E -- No --> G{score >= 0.40?}
    G -- Yes --> H[monitor]
    G -- No --> I[avoid]
    F & H --> J[Build legs via _BUILDERS]
    J --> K[_build_bull_call_spread / _build_iron_condor / etc.]
    K --> L[_compute_spread_risk<br/>Max profit, max loss, breakeven]
    L --> M[Ranked recommendation list]
```

### backtester.py — Internal Structure

```mermaid
graph LR
    subgraph "Data Preparation"
        A[_fetch_ohlcv 1yr] --> B[Compute indicators<br/>RSI, EMA, MACD, BB, VWAP, HVol]
    end

    subgraph "Walk-Forward Simulation"
        B --> C[For each trading day]
        C --> D[_check_entry_conditions]
        D -- triggered --> E[_simulate_strategy_pnl<br/>Black-Scholes pricing]
        E --> F[Record trade P&L]
    end

    subgraph "Aggregation"
        F --> G[Win rate, avg return,<br/>max drawdown, profit factor]
    end
```
