import yfinance as yf
import numpy as np
import os
import csv
import logging
from datetime import datetime, timezone


def _compute_max_pain(calls_df, puts_df):
    """Find the strike that minimizes total ITM option value across all OI."""
    try:
        all_strikes = sorted(set(calls_df["strike"].tolist() + puts_df["strike"].tolist()))
        if not all_strikes:
            return None

        min_pain = float("inf")
        max_pain_strike = None

        for test_strike in all_strikes:
            call_pain = 0
            for _, row in calls_df.iterrows():
                if test_strike > row["strike"]:
                    call_pain += (test_strike - row["strike"]) * row.get("openInterest", 0)

            put_pain = 0
            for _, row in puts_df.iterrows():
                if test_strike < row["strike"]:
                    put_pain += (row["strike"] - test_strike) * row.get("openInterest", 0)

            total = call_pain + put_pain
            if total < min_pain:
                min_pain = total
                max_pain_strike = test_strike

        return max_pain_strike
    except Exception:
        return None


def _find_unusual_activity(calls_df, puts_df, top_n=5):
    """Find strikes where volume > 2x openInterest, return top N by volume."""
    unusual = []
    for label, df in [("call", calls_df), ("put", puts_df)]:
        for _, row in df.iterrows():
            vol = row.get("volume", 0) or 0
            oi = row.get("openInterest", 0) or 0
            if oi > 0 and vol > 2 * oi:
                unusual.append({
                    "type": label,
                    "strike": row["strike"],
                    "volume": int(vol),
                    "openInterest": int(oi),
                    "ratio": round(vol / oi, 1),
                })
    unusual.sort(key=lambda x: x["volume"], reverse=True)
    return unusual[:top_n]


def _compute_skew(calls_df, puts_df, stock_price):
    """Compute IV skew: OTM put IV (5% OTM) minus OTM call IV (5% OTM)."""
    try:
        otm_put_target = stock_price * 0.95
        otm_call_target = stock_price * 1.05

        put_otm = puts_df[puts_df["strike"] <= stock_price].copy()
        call_otm = calls_df[calls_df["strike"] >= stock_price].copy()

        if put_otm.empty or call_otm.empty:
            return None

        put_otm["dist"] = abs(put_otm["strike"] - otm_put_target)
        call_otm["dist"] = abs(call_otm["strike"] - otm_call_target)

        nearest_put = put_otm.loc[put_otm["dist"].idxmin()]
        nearest_call = call_otm.loc[call_otm["dist"].idxmin()]

        put_iv = nearest_put.get("impliedVolatility", 0) or 0
        call_iv = nearest_call.get("impliedVolatility", 0) or 0

        if put_iv > 0 and call_iv > 0:
            return round(put_iv - call_iv, 4)
        return None
    except Exception:
        return None


def _persist_iv_snapshot(ticker, atm_iv, atm_call_premium, atm_put_premium, stock_price, atr_14=None):
    """Append daily ATM IV data to iv_history.csv for future IV Rank calculation."""
    try:
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

        # Determine write location
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        data_dir = os.path.join(base_dir, "data")

        # On Azure (read-only filesystem), write to /tmp
        if os.getenv("FUNCTIONS_WORKER_RUNTIME") == "python":
            data_dir = "/tmp"

        os.makedirs(data_dir, exist_ok=True)
        filepath = os.path.join(data_dir, "iv_history.csv")

        # Check if we already have an entry for today+ticker
        write_header = not os.path.exists(filepath)
        if not write_header:
            try:
                with open(filepath, "r") as f:
                    for line in f:
                        if line.startswith(f"{today},{ticker},"):
                            return  # already recorded today
            except Exception:
                pass

        with open(filepath, "a", newline="") as f:
            writer = csv.writer(f)
            if write_header:
                writer.writerow(["date", "ticker", "atm_iv", "atm_call_premium",
                                 "atm_put_premium", "stock_price", "atr_14"])
            writer.writerow([today, ticker,
                             round(atm_iv, 4) if atm_iv else "",
                             round(atm_call_premium, 2) if atm_call_premium else "",
                             round(atm_put_premium, 2) if atm_put_premium else "",
                             round(stock_price, 2) if stock_price else "",
                             round(atr_14, 2) if atr_14 else ""])
        logging.info(f"IV snapshot persisted for {ticker}: {atm_iv}")
    except Exception as e:
        logging.debug(f"Could not persist IV snapshot for {ticker}: {e}")


def get_options_data(ticker: str, stock_price: float = None, return_chain: bool = False) -> dict:
    """Analyze options chain for nearest monthly expiry. Returns ~20 metrics."""
    logging.info(f"Fetching options data for {ticker}")
    try:
        stock = yf.Ticker(ticker)
        expiries = stock.options
        if not expiries:
            return {"error": f"No options data for {ticker}", "ticker": ticker}

        # Find nearest monthly expiry (15-50 DTE target, fallback to first >7 DTE)
        now = datetime.now(timezone.utc).date()
        best_expiry = None
        best_dte = None

        for exp_str in expiries:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            dte = (exp_date - now).days
            if dte < 7:
                continue
            if 15 <= dte <= 50:
                if best_dte is None or abs(dte - 30) < abs(best_dte - 30):
                    best_expiry = exp_str
                    best_dte = dte
            elif best_expiry is None and dte > 7:
                best_expiry = exp_str
                best_dte = dte

        if not best_expiry:
            best_expiry = expiries[0]
            best_dte = (datetime.strptime(best_expiry, "%Y-%m-%d").date() - now).days

        # Fetch chain
        chain = stock.option_chain(best_expiry)
        calls_df = chain.calls
        puts_df = chain.puts

        if calls_df.empty and puts_df.empty:
            return {"error": f"Empty options chain for {ticker}", "ticker": ticker}

        # Get stock price if not provided
        if stock_price is None:
            try:
                stock_price = stock.info.get("regularMarketPrice") or stock.info.get("previousClose")
            except Exception:
                pass
        if stock_price is None and not calls_df.empty:
            stock_price = (calls_df["strike"].median() + puts_df["strike"].median()) / 2

        # ATM strike
        atm_strike = None
        if stock_price and not calls_df.empty:
            atm_strike = calls_df.iloc[(calls_df["strike"] - stock_price).abs().argsort()[:1]]["strike"].values[0]

        # ATM IV and premiums
        atm_call_iv = None
        atm_put_iv = None
        atm_call_premium = None
        atm_put_premium = None
        atm_iv = None

        if atm_strike is not None:
            atm_calls = calls_df[calls_df["strike"] == atm_strike]
            atm_puts = puts_df[puts_df["strike"] == atm_strike]

            if not atm_calls.empty:
                atm_call_iv = atm_calls.iloc[0].get("impliedVolatility")
                atm_call_premium = atm_calls.iloc[0].get("lastPrice")
            if not atm_puts.empty:
                atm_put_iv = atm_puts.iloc[0].get("impliedVolatility")
                atm_put_premium = atm_puts.iloc[0].get("lastPrice")

            ivs = [v for v in [atm_call_iv, atm_put_iv] if v and v > 0]
            atm_iv = round(np.mean(ivs), 4) if ivs else None

        # Premium as % of stock price
        atm_call_pct = round(atm_call_premium / stock_price * 100, 2) if atm_call_premium and stock_price else None
        atm_put_pct = round(atm_put_premium / stock_price * 100, 2) if atm_put_premium and stock_price else None

        # Put/Call ratios
        call_vol = calls_df["volume"].sum() if "volume" in calls_df.columns else 0
        put_vol = puts_df["volume"].sum() if "volume" in puts_df.columns else 0
        call_oi = calls_df["openInterest"].sum() if "openInterest" in calls_df.columns else 0
        put_oi = puts_df["openInterest"].sum() if "openInterest" in puts_df.columns else 0

        # Handle NaN sums
        call_vol = 0 if np.isnan(call_vol) else int(call_vol)
        put_vol = 0 if np.isnan(put_vol) else int(put_vol)
        call_oi = 0 if np.isnan(call_oi) else int(call_oi)
        put_oi = 0 if np.isnan(put_oi) else int(put_oi)

        pc_ratio_vol = round(put_vol / call_vol, 3) if call_vol > 0 else None
        pc_ratio_oi = round(put_oi / call_oi, 3) if call_oi > 0 else None

        # Max pain
        max_pain = _compute_max_pain(calls_df, puts_df)

        # Unusual activity
        unusual = _find_unusual_activity(calls_df, puts_df)

        # Skew
        skew = _compute_skew(calls_df, puts_df, stock_price) if stock_price else None

        result = {
            "ticker": ticker,
            "expiry": best_expiry,
            "dte": best_dte,
            "stock_price": stock_price,
            "atm_strike": atm_strike,
            "atm_iv": atm_iv,
            "atm_call_iv": atm_call_iv,
            "atm_put_iv": atm_put_iv,
            "atm_call_premium": atm_call_premium,
            "atm_put_premium": atm_put_premium,
            "atm_call_pct": atm_call_pct,
            "atm_put_pct": atm_put_pct,
            "pc_ratio_volume": pc_ratio_vol,
            "pc_ratio_oi": pc_ratio_oi,
            "total_call_volume": call_vol,
            "total_put_volume": put_vol,
            "total_call_oi": call_oi,
            "total_put_oi": put_oi,
            "max_pain": max_pain,
            "unusual_activity": unusual,
            "skew": skew,
            "iv_rank_note": "IV Rank unavailable — requires 52-week historical IV persistence",
        }

        # Persist daily IV snapshot
        if atm_iv is not None:
            _persist_iv_snapshot(ticker, atm_iv, atm_call_premium, atm_put_premium, stock_price)

        if return_chain:
            result["calls_df"] = calls_df
            result["puts_df"] = puts_df

        return result
    except Exception as e:
        logging.error(f"Error fetching options for {ticker}: {str(e)}")
        return {"error": f"Options data unavailable: {str(e)}", "ticker": ticker}
