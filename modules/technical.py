import yfinance as yf
import numpy as np
import pandas as pd
import logging


def _normalize_ohlcv(df: pd.DataFrame) -> pd.DataFrame:
    """Flatten MultiIndex columns and normalize to Title Case."""
    if df is None or df.empty:
        return pd.DataFrame()
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = [c[0] if isinstance(c, tuple) else c for c in df.columns]
    ren = {c: str(c).strip().title() for c in df.columns}
    df = df.rename(columns=ren)
    cols = [c for c in ["Open", "High", "Low", "Close", "Adj Close", "Volume"] if c in df.columns]
    return df[cols] if cols else df


def _fetch_ohlcv(ticker: str, period: str = "1y", interval: str = "1d") -> pd.DataFrame:
    """3-tier fallback data fetch, returns normalized DataFrame."""
    need = {"High", "Low", "Close", "Volume"}

    try:
        df = yf.download(ticker, period=period, interval=interval,
                         auto_adjust=True, progress=False, threads=False)
        df = _normalize_ohlcv(df)
        if not df.empty and need.issubset(df.columns):
            return df
    except Exception:
        pass

    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval, auto_adjust=True)
        hist = _normalize_ohlcv(hist)
        if not hist.empty and need.issubset(hist.columns):
            return hist
    except Exception:
        pass

    try:
        raw = yf.download(ticker, period=period, interval=interval,
                          auto_adjust=False, progress=False, threads=False)
        raw = _normalize_ohlcv(raw)
        if not raw.empty and need.issubset(raw.columns):
            return raw
    except Exception:
        pass

    return pd.DataFrame()


def _compute_rsi(close: pd.Series, period: int = 14) -> pd.Series:
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def _compute_anchored_vwap(data: pd.DataFrame, anchor_date: str = None) -> tuple:
    """Compute VWAP anchored from a specific date. Returns (vwap_value, anchor_label)."""
    if anchor_date:
        try:
            anchor = pd.Timestamp(anchor_date)
            mask = data.index >= anchor
            if mask.any():
                subset = data.loc[mask]
                tp = (subset["High"] + subset["Low"] + subset["Close"]) / 3
                vol = subset["Volume"].replace(0, np.nan)
                vwap = (tp * subset["Volume"]).cumsum() / vol.cumsum()
                return float(vwap.iloc[-1]), f"earnings_{anchor_date}"
        except Exception:
            pass

    # Fallback: 20-day rolling VWAP
    tp = (data["High"] + data["Low"] + data["Close"]) / 3
    vol_cum = data["Volume"].rolling(20).sum().replace(0, np.nan)
    vwap_rolling = (tp * data["Volume"]).rolling(20).sum() / vol_cum
    if not vwap_rolling.dropna().empty:
        return float(vwap_rolling.iloc[-1]), "rolling_20d"

    return None, "unavailable"


def get_technical_indicators(ticker: str, last_earnings_date: str = None) -> dict:
    """Compute 22 technical indicators from 1-year daily data."""
    logging.info(f"Fetching technicals for {ticker}")
    try:
        data = _fetch_ohlcv(ticker, period="1y", interval="1d")
        if data.empty or len(data) < 50:
            return {"error": f"Insufficient data for {ticker} (rows={len(data)})", "ticker": ticker}

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        # EMAs
        ema9 = close.ewm(span=9, adjust=False).mean()
        ema20 = close.ewm(span=20, adjust=False).mean()
        ema12 = close.ewm(span=12, adjust=False).mean()
        ema26 = close.ewm(span=26, adjust=False).mean()

        # RSI
        rsi = _compute_rsi(close, 14)

        # MACD
        macd_line = ema12 - ema26
        macd_signal = macd_line.ewm(span=9, adjust=False).mean()
        macd_hist = macd_line - macd_signal

        # Bollinger Bands
        sma20 = close.rolling(20).mean()
        std20 = close.rolling(20).std()
        bb_upper = sma20 + 2 * std20
        bb_lower = sma20 - 2 * std20
        bb_width = (bb_upper - bb_lower) / sma20

        # SMAs
        sma50 = close.rolling(50).mean()
        sma200 = close.rolling(200).mean()

        # Volume ratio
        vol_avg_20 = volume.rolling(20).mean()
        vol_ratio = volume / vol_avg_20.replace(0, np.nan)

        # Support / Resistance (20-day)
        support_20d = low.rolling(20).min()
        resistance_20d = high.rolling(20).max()

        # 52-week high/low
        week52_high = float(high.max())
        week52_low = float(low.min())

        # % changes
        pct_1d = close.pct_change(1) * 100
        pct_5d = close.pct_change(5) * 100
        pct_1mo = close.pct_change(21) * 100
        pct_3mo = close.pct_change(63) * 100

        # Anchored VWAP
        vwap_val, vwap_anchor = _compute_anchored_vwap(data, last_earnings_date)

        # Extract latest values
        last_idx = -1
        price = float(close.iloc[last_idx])

        def _safe_float(series, idx=-1):
            try:
                v = series.iloc[idx]
                return float(v) if not np.isnan(v) else None
            except Exception:
                return None

        return {
            "ticker": ticker,
            "price": price,
            "EMA_9": _safe_float(ema9),
            "EMA_20": _safe_float(ema20),
            "RSI": _safe_float(rsi),
            "VWAP": vwap_val,
            "VWAP_anchor": vwap_anchor,
            "MACD_line": _safe_float(macd_line),
            "MACD_signal": _safe_float(macd_signal),
            "MACD_histogram": _safe_float(macd_hist),
            "BB_upper": _safe_float(bb_upper),
            "BB_lower": _safe_float(bb_lower),
            "BB_width": _safe_float(bb_width),
            "SMA_50": _safe_float(sma50),
            "SMA_200": _safe_float(sma200),
            "volume_ratio": _safe_float(vol_ratio),
            "support_20d": _safe_float(support_20d),
            "resistance_20d": _safe_float(resistance_20d),
            "week_52_high": week52_high,
            "week_52_low": week52_low,
            "pct_change_1d": _safe_float(pct_1d),
            "pct_change_5d": _safe_float(pct_5d),
            "pct_change_1mo": _safe_float(pct_1mo),
            "pct_change_3mo": _safe_float(pct_3mo),
        }
    except Exception as e:
        logging.error(f"Error fetching technicals for {ticker}: {str(e)}")
        return {"error": f"Technicals unavailable: {str(e)}", "ticker": ticker}
