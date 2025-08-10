#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import numpy as np
import pandas as pd
import yfinance as yf

# ---------------------------
# Data fetching (robust)
# ---------------------------

def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """
    Flatten possible MultiIndex columns, normalize names to Title Case,
    and keep standard OHLCV columns when present.
    """
    if df is None or df.empty:
        return pd.DataFrame()

    # ('Close','AAPL') -> 'Close'
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]

    # Normalize names: close->Close, volume->Volume, etc.
    ren = {c: str(c).strip().title() for c in df.columns}
    df = df.rename(columns=ren)

    # Reorder/keep only expected columns (when available)
    cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    return df[cols] if cols else df


def _fetch_ohlcv(ticker: str, period: str, interval: str, auto_adjust: bool = True) -> pd.DataFrame:
    """
    Try yf.download first; if schema is odd/missing OHLCV, fallback to Ticker().history();
    finally try without auto_adjust. Returns a normalized DataFrame or empty on failure.
    """
    need = {"High", "Low", "Close", "Volume"}

    # Attempt 1: download()
    try:
        df = yf.download(
            ticker, period=period, interval=interval,
            auto_adjust=auto_adjust, progress=False, threads=False
        )
        df = _normalize_ohlcv(df)
        if not df.empty and need.issubset(df.columns):
            return df
    except Exception:
        pass

    # Attempt 2: Ticker().history()
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=auto_adjust)
        hist = _normalize_ohlcv(hist)
        if not hist.empty and need.issubset(hist.columns):
            return hist
    except Exception:
        pass

    # Attempt 3: raw (auto_adjust=False)
    if auto_adjust:
        try:
            raw = yf.download(
                ticker, period=period, interval=interval,
                auto_adjust=False, progress=False, threads=False
            )
            raw = _normalize_ohlcv(raw)
            if not raw.empty and need.issubset(raw.columns):
                return raw
        except Exception:
            pass

    return pd.DataFrame()


# ---------------------------
# Indicator calculations
# ---------------------------

def _compute_ema(series: pd.Series, span: int) -> pd.Series:
    return series.ewm(span=span, adjust=False).mean()

def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    """
    Classic Wilder RSI (using simple rolling averages here).
    min_periods guards against early NaNs.
    """
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def _compute_vwap(close: pd.Series, volume: pd.Series) -> pd.Series:
    vol_cum = volume.cumsum().replace(0, np.nan)  # avoid divide-by-zero
    return (close * volume).cumsum() / vol_cum

def _compute_atr(high: pd.Series, low: pd.Series, close: pd.Series, period: int = 14) -> pd.Series:
    """
    ATR via True Range rolling mean.
    """
    hl = high - low
    h_pc = (high - close.shift()).abs()
    l_pc = (low  - close.shift()).abs()
    tr = pd.concat([hl, h_pc, l_pc], axis=1).max(axis=1)
    return tr.rolling(window=period, min_periods=period).mean()


# ---------------------------
# Public API
# ---------------------------

def evaluate_strategy(ticker: str, period: str = "6mo", interval: str = "1d") -> dict:
    """
    Returns a dict with entry/exit boolean signals, latest indicators, and reasons.
    Provides clear 'error' messages when upstream data is insufficient.
    """
    try:
        data = _fetch_ohlcv(ticker, period=period, interval=interval, auto_adjust=True)

        need = {"High", "Low", "Close", "Volume"}
        if data.empty or len(data) < 40:
            return {
                "error": f"Not enough data to evaluate. cols={list(data.columns)} len={len(data)}",
                "ticker": ticker
            }
        missing = need - set(data.columns)
        if missing:
            return {
                "error": f"Missing columns: {missing} | cols={list(data.columns)}",
                "ticker": ticker
            }

        # Indicators
        data["EMA_9"]   = _compute_ema(data["Close"], 9)
        data["EMA_20"]  = _compute_ema(data["Close"], 20)
        data["RSI"]     = _compute_rsi(data["Close"], 14)
        data["VWAP"]    = _compute_vwap(data["Close"], data["Volume"])
        data["ATR_14"]  = _compute_atr(data["High"], data["Low"], data["Close"], 14)

        # Clean up NaNs from indicator warm-up
        data = data.dropna()
        if len(data) < 2:
            return {"error": "Insufficient data after indicator calculation.", "ticker": ticker}

        latest   = data.iloc[-1]
        previous = data.iloc[-2]

        # Scalar-safe comparisons
        rsi_latest   = float(latest["RSI"])
        price_latest = float(latest["Close"])
        vwap_latest  = float(latest["VWAP"])
        ema9_latest  = float(latest["EMA_9"])
        ema20_latest = float(latest["EMA_20"])
        ema9_prev    = float(previous["EMA_9"])
        ema20_prev   = float(previous["EMA_20"])
        atr_latest   = float(latest["ATR_14"]) if not np.isnan(latest["ATR_14"]) else None

        # Entry / Exit logic
        entry_signal = all([
            rsi_latest < 35,
            price_latest < vwap_latest,
            (ema9_prev < ema20_prev) and (ema9_latest > ema20_latest)
        ])

        exit_signal = all([
            rsi_latest > 65,
            price_latest > vwap_latest,
            (ema9_prev > ema20_prev) and (ema9_latest < ema20_latest)
        ])

        return {
            "ticker": ticker,
            "entry_signal": bool(entry_signal),
            "exit_signal": bool(exit_signal),
            "latest_price": price_latest,
            "RSI": rsi_latest,
            "VWAP": vwap_latest,
            "EMA_9": ema9_latest,
            "EMA_20": ema20_latest,
            "ATR_14": atr_latest,
            "reasons": {
                "entry": {
                    "RSI < 35": rsi_latest < 35,
                    "Price < VWAP": price_latest < vwap_latest,
                    "EMA 9 crossover up": (ema9_prev < ema20_prev) and (ema9_latest > ema20_latest),
                },
                "exit": {
                    "RSI > 65": rsi_latest > 65,
                    "Price > VWAP": price_latest > vwap_latest,
                    "EMA 9 crossover down": (ema9_prev > ema20_prev) and (ema9_latest < ema20_latest),
                },
            },
        }

    except Exception as e:
        # Always return error as a dict for the report layer to display
        return {"error": str(e), "ticker": ticker}