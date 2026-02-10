"""Entry/Exit Signal Backtester.

Backtests the existing entry/exit signal framework (RSI < 35, Price < VWAP,
EMA crossover) against historical data using walk-forward simulation.
"""

import logging
import numpy as np
import pandas as pd


def _compute_rsi(close, period=14):
    delta = close.diff()
    gain = delta.where(delta > 0, 0.0)
    loss = -delta.where(delta < 0, 0.0)
    avg_gain = gain.rolling(window=period, min_periods=period).mean()
    avg_loss = loss.rolling(window=period, min_periods=period).mean()
    rs = avg_gain / avg_loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))


def backtest_entry_exit(ticker, lookback_days=252, max_hold_days=30):
    """Backtest entry/exit signals against historical data.

    Entry conditions (all must be true):
    - RSI < 35
    - Price < VWAP (20-day rolling)
    - EMA9 crosses above EMA20

    Exit conditions (any true):
    - RSI > 65 AND Price > VWAP AND EMA9 crosses below EMA20
    - Max holding period exceeded

    Args:
        ticker: Stock ticker symbol
        lookback_days: Number of trading days (default: 252 = 1 year)
        max_hold_days: Maximum days to hold a position (default: 30)

    Returns:
        dict with backtest statistics
    """
    logging.info(f"Backtesting entry/exit signals for {ticker}")

    try:
        from technical import _fetch_ohlcv
        data = _fetch_ohlcv(ticker, period="1y", interval="1d")

        if data.empty or len(data) < 60:
            return {"error": f"Insufficient data ({len(data)} rows)", "ticker": ticker}

        close = data["Close"]
        high = data["High"]
        low = data["Low"]
        volume = data["Volume"]

        # Indicators
        data["EMA_9"] = close.ewm(span=9, adjust=False).mean()
        data["EMA_20"] = close.ewm(span=20, adjust=False).mean()
        data["RSI"] = _compute_rsi(close)

        # 20-day rolling VWAP
        tp = (high + low + close) / 3
        vol_cum = volume.rolling(20).sum().replace(0, np.nan)
        data["VWAP"] = (tp * volume).rolling(20).sum() / vol_cum

        # Drop NaN warmup
        data = data.dropna(subset=["RSI", "EMA_9", "EMA_20", "VWAP"])

        if len(data) < 20:
            return {"error": "Insufficient data after warmup", "ticker": ticker}

        if len(data) > lookback_days:
            data = data.iloc[-lookback_days:]

        # Walk forward
        trades = []
        in_position = False
        entry_price = None
        hold_days = 0

        for i in range(1, len(data)):
            row = data.iloc[i]
            prev = data.iloc[i - 1]

            price = float(row["Close"])
            rsi = float(row["RSI"])
            vwap = float(row["VWAP"])
            ema9 = float(row["EMA_9"])
            ema20 = float(row["EMA_20"])
            ema9_prev = float(prev["EMA_9"])
            ema20_prev = float(prev["EMA_20"])

            if np.isnan(rsi) or np.isnan(vwap) or np.isnan(ema9):
                continue

            if not in_position:
                # Entry: RSI < 35, Price < VWAP, EMA9 crosses above EMA20
                ema_crossover_up = (ema9_prev < ema20_prev) and (ema9 > ema20)
                if rsi < 35 and price < vwap and ema_crossover_up:
                    in_position = True
                    entry_price = price
                    hold_days = 0
            else:
                hold_days += 1

                # Exit: RSI > 65, Price > VWAP, EMA9 crosses below EMA20
                ema_crossover_down = (ema9_prev > ema20_prev) and (ema9 < ema20)
                exit_signal = (rsi > 65 and price > vwap and ema_crossover_down)

                if exit_signal or hold_days >= max_hold_days:
                    pnl = price - entry_price
                    pnl_pct = pnl / entry_price * 100
                    trades.append({
                        "entry_price": entry_price,
                        "exit_price": price,
                        "hold_days": hold_days,
                        "pnl": pnl,
                        "pnl_pct": pnl_pct,
                        "exit_reason": "signal" if exit_signal else "max_hold",
                    })
                    in_position = False

        # Aggregate
        period_str = f"{data.index[0].strftime('%Y-%m-%d')} to {data.index[-1].strftime('%Y-%m-%d')}"

        if not trades:
            return {
                "ticker": ticker,
                "strategy": "ENTRY_EXIT_SIGNALS",
                "period": period_str,
                "total_signals": 0,
                "trades_taken": 0,
                "wins": 0,
                "losses": 0,
                "win_rate": 0,
                "avg_return_pct": 0,
                "max_drawdown_pct": 0,
                "profit_factor": 0,
                "avg_holding_days": 0,
                "note": "No entry signals triggered during lookback period",
            }

        wins = [t for t in trades if t["pnl"] > 0]
        losses = [t for t in trades if t["pnl"] <= 0]
        gross_profit = sum(t["pnl"] for t in wins) if wins else 0
        gross_loss = abs(sum(t["pnl"] for t in losses)) if losses else 0

        # Max drawdown
        cum_pnl = np.cumsum([t["pnl"] for t in trades])
        running_max = np.maximum.accumulate(cum_pnl)
        drawdowns = cum_pnl - running_max
        max_dd = float(np.min(drawdowns)) if len(drawdowns) > 0 else 0
        max_dd_pct = max_dd / trades[0]["entry_price"] * 100 if trades else 0

        return {
            "ticker": ticker,
            "strategy": "ENTRY_EXIT_SIGNALS",
            "period": period_str,
            "total_signals": len(trades),
            "trades_taken": len(trades),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(trades),
            "avg_return_pct": round(np.mean([t["pnl_pct"] for t in trades]), 1),
            "max_drawdown_pct": round(max_dd_pct, 1),
            "profit_factor": round(gross_profit / gross_loss, 2) if gross_loss > 0 else float("inf"),
            "avg_holding_days": round(np.mean([t["hold_days"] for t in trades]), 0),
            "signal_exits": sum(1 for t in trades if t["exit_reason"] == "signal"),
            "timeout_exits": sum(1 for t in trades if t["exit_reason"] == "max_hold"),
            "note": "Walk-forward backtest of RSI/VWAP/EMA crossover signals",
        }

    except Exception as e:
        logging.error(f"Entry/exit backtest error for {ticker}: {e}")
        return {"error": str(e), "ticker": ticker}
