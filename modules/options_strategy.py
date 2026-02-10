"""Options Strategy Engine — 7 defined-risk strategies with scoring and risk profiles.

Evaluates market conditions against strategy requirements, selects optimal strikes
from the options chain, and computes exact risk profiles (max profit/loss/breakeven).
"""

import logging
import numpy as np


# ---------------------------------------------------------------------------
# Strategy condition definitions
# ---------------------------------------------------------------------------

STRATEGY_CONDITIONS = {
    "COVERED_CALL": {
        "description": "Sell OTM call against long stock for income",
        "market_view": "neutral-bullish",
        "conditions": {
            "price_above_sma50": {"weight": 0.25, "label": "Price > SMA50"},
            "iv_moderate": {"weight": 0.25, "label": "IV 25-45%"},
            "rsi_neutral": {"weight": 0.20, "label": "RSI 40-60"},
            "trend_up": {"weight": 0.15, "label": "EMA9 > EMA20"},
            "not_near_earnings": {"weight": 0.15, "label": "No earnings within DTE"},
        },
    },
    "CASH_SECURED_PUT": {
        "description": "Sell put at/near money, bullish on dip",
        "market_view": "bullish on dip",
        "conditions": {
            "price_near_support": {"weight": 0.25, "label": "Price near support"},
            "iv_elevated": {"weight": 0.25, "label": "IV > 30%"},
            "rsi_low": {"weight": 0.20, "label": "RSI < 40"},
            "price_above_sma200": {"weight": 0.15, "label": "Price > SMA200"},
            "not_near_earnings": {"weight": 0.15, "label": "No earnings within DTE"},
        },
    },
    "BULL_CALL_SPREAD": {
        "description": "Buy ATM call, sell OTM call — directional up, limited risk",
        "market_view": "bullish",
        "conditions": {
            "ema_bullish": {"weight": 0.25, "label": "EMA9 > EMA20"},
            "price_above_vwap": {"weight": 0.20, "label": "Price > VWAP"},
            "iv_moderate": {"weight": 0.20, "label": "IV moderate (20-50%)"},
            "rsi_not_overbought": {"weight": 0.20, "label": "RSI < 65"},
            "macd_bullish": {"weight": 0.15, "label": "MACD histogram > 0"},
        },
    },
    "BEAR_CALL_SPREAD": {
        "description": "Sell ATM/OTM call, buy higher call — directional down, credit",
        "market_view": "bearish",
        "conditions": {
            "ema_bearish": {"weight": 0.25, "label": "EMA9 < EMA20"},
            "rsi_high": {"weight": 0.25, "label": "RSI > 65"},
            "iv_elevated": {"weight": 0.20, "label": "IV > 40%"},
            "price_below_vwap": {"weight": 0.15, "label": "Price < VWAP"},
            "macd_bearish": {"weight": 0.15, "label": "MACD histogram < 0"},
        },
    },
    "IRON_CONDOR": {
        "description": "Sell OTM put + call, buy wings — range-bound theta play",
        "market_view": "neutral/range-bound",
        "conditions": {
            "bb_narrow": {"weight": 0.30, "label": "BB width < 0.06"},
            "iv_elevated": {"weight": 0.25, "label": "IV 40-70%"},
            "rsi_neutral": {"weight": 0.20, "label": "RSI 40-60"},
            "no_signals": {"weight": 0.15, "label": "No entry/exit signals"},
            "not_near_earnings": {"weight": 0.10, "label": "No earnings within DTE"},
        },
    },
    "PROTECTIVE_PUT": {
        "description": "Buy OTM put as insurance on long stock position",
        "market_view": "long stock, need hedge",
        "conditions": {
            "price_near_resistance": {"weight": 0.25, "label": "Price near resistance"},
            "near_earnings": {"weight": 0.25, "label": "Earnings within DTE"},
            "rsi_high": {"weight": 0.20, "label": "RSI > 60"},
            "iv_not_extreme": {"weight": 0.15, "label": "IV < 60%"},
            "trend_up": {"weight": 0.15, "label": "Price > SMA50 (worth protecting)"},
        },
    },
    "LONG_STRADDLE": {
        "description": "Buy ATM call + put — expecting big move",
        "market_view": "volatile/uncertain",
        "conditions": {
            "near_earnings": {"weight": 0.30, "label": "Earnings within 5-15 days"},
            "unusual_activity": {"weight": 0.25, "label": "Unusual options activity"},
            "iv_not_extreme": {"weight": 0.20, "label": "IV < 50% (not already priced in)"},
            "bb_narrow": {"weight": 0.15, "label": "BB squeeze (volatility expansion due)"},
            "volume_spike": {"weight": 0.10, "label": "Volume ratio > 1.5"},
        },
    },
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _find_strike_near(chain_df, target_price, direction=None):
    """Find the nearest liquid strike to target_price.

    Args:
        chain_df: DataFrame with 'strike' column (and optionally 'volume', 'openInterest')
        target_price: Target strike price
        direction: 'above' for OTM calls, 'below' for OTM puts, None for nearest
    """
    if chain_df is None or chain_df.empty:
        return None

    df = chain_df.copy()

    # Filter by direction if specified
    if direction == "above":
        df = df[df["strike"] >= target_price]
    elif direction == "below":
        df = df[df["strike"] <= target_price]

    if df.empty:
        return None

    # Find nearest by price distance
    df = df.copy()
    df["_dist"] = abs(df["strike"] - target_price)
    nearest = df.loc[df["_dist"].idxmin()]
    return nearest


def _get_premium(row):
    """Extract premium from an option chain row, preferring lastPrice."""
    if row is None:
        return None
    for col in ["lastPrice", "ask", "bid"]:
        v = row.get(col)
        if v is not None and not (isinstance(v, float) and np.isnan(v)) and v > 0:
            return float(v)
    return None


def _compute_spread_risk(long_premium, short_premium, spread_width, spread_type="debit"):
    """Compute risk profile for a vertical spread.

    Args:
        long_premium: Premium paid for long leg
        short_premium: Premium received for short leg
        spread_width: Distance between strikes
        spread_type: 'debit' (bull call/bear put) or 'credit' (bear call/bull put)
    """
    if long_premium is None or short_premium is None:
        return None

    if spread_type == "debit":
        net_debit = long_premium - short_premium
        if net_debit <= 0:
            return None
        max_loss = net_debit * 100
        max_profit = (spread_width - net_debit) * 100
        breakeven = None  # caller computes based on strategy type
    else:  # credit
        net_credit = short_premium - long_premium
        if net_credit <= 0:
            return None
        max_profit = net_credit * 100
        max_loss = (spread_width - net_credit) * 100
        breakeven = None

    if max_loss <= 0:
        return None

    return {
        "max_profit": round(max_profit, 2),
        "max_loss": round(max_loss, 2),
        "risk_reward_ratio": round(max_profit / max_loss, 2),
        "net_debit": round(net_debit, 2) if spread_type == "debit" else None,
        "net_credit": round(net_credit, 2) if spread_type == "credit" else None,
    }


def _score_conditions(condition_results):
    """Score strategy based on weighted condition results.

    Args:
        condition_results: dict of {condition_name: {"met": bool, "weight": float, "label": str}}

    Returns:
        (score, conditions_met_labels)
    """
    total_weight = 0
    met_weight = 0
    met_labels = []

    for name, info in condition_results.items():
        w = info["weight"]
        total_weight += w
        if info["met"]:
            met_weight += w
            met_labels.append(info["label"])

    score = met_weight / total_weight if total_weight > 0 else 0
    return round(score, 3), met_labels


# ---------------------------------------------------------------------------
# Condition evaluators
# ---------------------------------------------------------------------------

def _evaluate_conditions(strategy_name, ta, fa, options_data, strat):
    """Evaluate all conditions for a given strategy against current market data.

    Returns dict of {condition_name: {"met": bool, "weight": float, "label": str}}
    """
    strategy_def = STRATEGY_CONDITIONS[strategy_name]
    results = {}

    price = ta.get("price")
    rsi = ta.get("RSI")
    ema9 = ta.get("EMA_9")
    ema20 = ta.get("EMA_20")
    sma50 = ta.get("SMA_50")
    sma200 = ta.get("SMA_200")
    vwap = ta.get("VWAP")
    bb_width = ta.get("BB_width")
    macd_hist = ta.get("MACD_histogram")
    vol_ratio = ta.get("volume_ratio")
    support = ta.get("support_20d")
    resistance = ta.get("resistance_20d")

    atm_iv = options_data.get("atm_iv") if options_data else None
    unusual = options_data.get("unusual_activity", []) if options_data else []
    dte = options_data.get("dte") if options_data else None

    days_to_earnings = fa.get("days_to_earnings") if fa else None
    entry_signal = strat.get("entry_signal", False) if strat else False
    exit_signal = strat.get("exit_signal", False) if strat else False

    for cond_name, cond_def in strategy_def["conditions"].items():
        met = False

        if cond_name == "price_above_sma50":
            met = price is not None and sma50 is not None and price > sma50

        elif cond_name == "price_above_sma200":
            met = price is not None and sma200 is not None and price > sma200

        elif cond_name == "iv_moderate":
            if strategy_name == "BULL_CALL_SPREAD":
                met = atm_iv is not None and 0.20 <= atm_iv <= 0.50
            else:
                met = atm_iv is not None and 0.25 <= atm_iv <= 0.45

        elif cond_name == "iv_elevated":
            if strategy_name == "IRON_CONDOR":
                met = atm_iv is not None and 0.40 <= atm_iv <= 0.70
            elif strategy_name == "BEAR_CALL_SPREAD":
                met = atm_iv is not None and atm_iv > 0.40
            else:
                met = atm_iv is not None and atm_iv > 0.30

        elif cond_name == "iv_not_extreme":
            if strategy_name == "LONG_STRADDLE":
                met = atm_iv is not None and atm_iv < 0.50
            else:
                met = atm_iv is not None and atm_iv < 0.60

        elif cond_name == "rsi_neutral":
            met = rsi is not None and 40 <= rsi <= 60

        elif cond_name == "rsi_low":
            met = rsi is not None and rsi < 40

        elif cond_name == "rsi_high":
            met = rsi is not None and rsi > 65 if strategy_name == "BEAR_CALL_SPREAD" else (
                rsi is not None and rsi > 60
            )

        elif cond_name == "rsi_not_overbought":
            met = rsi is not None and rsi < 65

        elif cond_name == "ema_bullish" or cond_name == "trend_up":
            met = ema9 is not None and ema20 is not None and ema9 > ema20

        elif cond_name == "ema_bearish":
            met = ema9 is not None and ema20 is not None and ema9 < ema20

        elif cond_name == "price_above_vwap":
            met = price is not None and vwap is not None and price > vwap

        elif cond_name == "price_below_vwap":
            met = price is not None and vwap is not None and price < vwap

        elif cond_name == "price_near_support":
            if price is not None and support is not None and resistance is not None:
                total_range = resistance - support
                if total_range > 0:
                    met = (price - support) / total_range < 0.3

        elif cond_name == "price_near_resistance":
            if price is not None and support is not None and resistance is not None:
                total_range = resistance - support
                if total_range > 0:
                    met = (resistance - price) / total_range < 0.3

        elif cond_name == "bb_narrow":
            met = bb_width is not None and bb_width < 0.06

        elif cond_name == "macd_bullish":
            met = macd_hist is not None and macd_hist > 0

        elif cond_name == "macd_bearish":
            met = macd_hist is not None and macd_hist < 0

        elif cond_name == "no_signals":
            met = not entry_signal and not exit_signal

        elif cond_name == "not_near_earnings":
            if days_to_earnings is None:
                met = True  # assume safe if unknown
            else:
                met = days_to_earnings is not None and (
                    days_to_earnings < 0 or days_to_earnings > (dte or 30)
                )

        elif cond_name == "near_earnings":
            if strategy_name == "LONG_STRADDLE":
                met = days_to_earnings is not None and 5 <= days_to_earnings <= 15
            else:
                met = days_to_earnings is not None and 0 < days_to_earnings <= (dte or 30)

        elif cond_name == "unusual_activity":
            met = len(unusual) >= 2

        elif cond_name == "volume_spike":
            met = vol_ratio is not None and vol_ratio > 1.5

        results[cond_name] = {
            "met": met,
            "weight": cond_def["weight"],
            "label": cond_def["label"],
        }

    return results


# ---------------------------------------------------------------------------
# Strategy builders — construct legs and risk profiles
# ---------------------------------------------------------------------------

def _build_covered_call(ta, options_data, calls_df, puts_df, expiry):
    """Covered call: sell 1-2 strikes OTM from ATM."""
    price = ta.get("price")
    if calls_df is None or calls_df.empty or price is None:
        return None

    # Find strike 1-2 strikes OTM
    otm_calls = calls_df[calls_df["strike"] > price].sort_values("strike")
    if len(otm_calls) < 2:
        return None

    # Pick 2nd OTM strike (1 strike above ATM)
    sell_row = otm_calls.iloc[1] if len(otm_calls) > 1 else otm_calls.iloc[0]
    sell_strike = float(sell_row["strike"])
    sell_premium = _get_premium(sell_row)
    if sell_premium is None:
        return None

    legs = [
        {"action": "SELL", "type": "call", "strike": sell_strike,
         "premium": sell_premium, "expiry": expiry},
    ]

    # Risk: max profit = premium + (strike - price) if called away
    max_profit = round((sell_premium + (sell_strike - price)) * 100, 2)
    max_loss_note = "Underlying risk minus premium received"
    breakeven = round(price - sell_premium, 2)

    return {
        "legs": legs,
        "risk_profile": {
            "max_profit": max_profit,
            "max_loss": round((price - sell_premium) * 100, 2),  # stock to zero minus premium
            "breakeven": breakeven,
            "risk_reward_ratio": None,  # asymmetric
        },
    }


def _build_cash_secured_put(ta, options_data, calls_df, puts_df, expiry):
    """Cash-secured put: sell ATM or 1 strike OTM."""
    price = ta.get("price")
    if puts_df is None or puts_df.empty or price is None:
        return None

    # ATM put
    atm_row = _find_strike_near(puts_df, price)
    if atm_row is None:
        return None

    sell_strike = float(atm_row["strike"])
    sell_premium = _get_premium(atm_row)
    if sell_premium is None:
        return None

    legs = [
        {"action": "SELL", "type": "put", "strike": sell_strike,
         "premium": sell_premium, "expiry": expiry},
    ]

    max_profit = round(sell_premium * 100, 2)
    breakeven = round(sell_strike - sell_premium, 2)
    max_loss = round(breakeven * 100, 2)  # assigned at breakeven to zero

    return {
        "legs": legs,
        "risk_profile": {
            "max_profit": max_profit,
            "max_loss": max_loss,
            "breakeven": breakeven,
            "risk_reward_ratio": None,  # asymmetric
        },
    }


def _build_bull_call_spread(ta, options_data, calls_df, puts_df, expiry):
    """Bull call spread: buy ATM call, sell call 5-10% OTM."""
    price = ta.get("price")
    if calls_df is None or calls_df.empty or price is None:
        return None

    # Buy ATM call
    buy_row = _find_strike_near(calls_df, price)
    if buy_row is None:
        return None
    buy_strike = float(buy_row["strike"])
    buy_premium = _get_premium(buy_row)

    # Sell OTM call (target 5-10% above price, ~$5-10 spread width)
    target_sell = price * 1.05
    min_spread = max(5.0, price * 0.03)  # at least $5 or 3% wide
    max_spread = max(10.0, price * 0.10)  # at most $10 or 10% wide

    otm_calls = calls_df[
        (calls_df["strike"] > buy_strike + min_spread) &
        (calls_df["strike"] <= buy_strike + max_spread)
    ].sort_values("strike")

    if otm_calls.empty:
        # Fallback: just pick next few strikes up
        otm_calls = calls_df[calls_df["strike"] > buy_strike].sort_values("strike").head(5)
        if len(otm_calls) >= 2:
            otm_calls = otm_calls.iloc[1:3]  # skip very next, get 2nd-3rd OTM

    if otm_calls.empty:
        return None

    sell_row = otm_calls.iloc[0]
    sell_strike = float(sell_row["strike"])
    sell_premium = _get_premium(sell_row)

    if buy_premium is None or sell_premium is None:
        return None

    spread_width = sell_strike - buy_strike
    risk = _compute_spread_risk(buy_premium, sell_premium, spread_width, "debit")
    if risk is None:
        return None

    net_debit = buy_premium - sell_premium
    breakeven = round(buy_strike + net_debit, 2)
    risk["breakeven"] = breakeven

    legs = [
        {"action": "BUY", "type": "call", "strike": buy_strike,
         "premium": buy_premium, "expiry": expiry},
        {"action": "SELL", "type": "call", "strike": sell_strike,
         "premium": sell_premium, "expiry": expiry},
    ]

    return {"legs": legs, "risk_profile": risk}


def _build_bear_call_spread(ta, options_data, calls_df, puts_df, expiry):
    """Bear call spread: sell ATM/slightly OTM call, buy call 1-2 strikes higher."""
    price = ta.get("price")
    if calls_df is None or calls_df.empty or price is None:
        return None

    # Sell near ATM or slightly OTM call
    sell_row = _find_strike_near(calls_df, price, direction="above")
    if sell_row is None:
        return None
    sell_strike = float(sell_row["strike"])
    sell_premium = _get_premium(sell_row)

    # Buy 1-2 strikes higher
    higher_calls = calls_df[calls_df["strike"] > sell_strike].sort_values("strike")
    if higher_calls.empty:
        return None

    buy_idx = min(1, len(higher_calls) - 1)  # prefer 2nd strike up
    buy_row = higher_calls.iloc[buy_idx]
    buy_strike = float(buy_row["strike"])
    buy_premium = _get_premium(buy_row)

    if sell_premium is None or buy_premium is None:
        return None

    spread_width = buy_strike - sell_strike
    risk = _compute_spread_risk(buy_premium, sell_premium, spread_width, "credit")
    if risk is None:
        return None

    net_credit = sell_premium - buy_premium
    breakeven = round(sell_strike + net_credit, 2)
    risk["breakeven"] = breakeven

    legs = [
        {"action": "SELL", "type": "call", "strike": sell_strike,
         "premium": sell_premium, "expiry": expiry},
        {"action": "BUY", "type": "call", "strike": buy_strike,
         "premium": buy_premium, "expiry": expiry},
    ]

    return {"legs": legs, "risk_profile": risk}


def _build_iron_condor(ta, options_data, calls_df, puts_df, expiry):
    """Iron condor: sell OTM put + call (~1 StdDev), buy wings 1 strike wider."""
    price = ta.get("price")
    bb_upper = ta.get("BB_upper")
    bb_lower = ta.get("BB_lower")

    if (calls_df is None or puts_df is None or calls_df.empty or puts_df.empty
            or price is None):
        return None

    # Use Bollinger Bands as approximate 1-StdDev range, or 5% OTM
    if bb_upper and bb_lower:
        upper_target = bb_upper
        lower_target = bb_lower
    else:
        upper_target = price * 1.05
        lower_target = price * 0.95

    # Sell OTM call
    sell_call_row = _find_strike_near(calls_df, upper_target, direction="above")
    if sell_call_row is None:
        return None
    sell_call_strike = float(sell_call_row["strike"])
    sell_call_premium = _get_premium(sell_call_row)

    # Buy call 1 strike wider
    wider_calls = calls_df[calls_df["strike"] > sell_call_strike].sort_values("strike")
    if wider_calls.empty:
        return None
    buy_call_row = wider_calls.iloc[0]
    buy_call_strike = float(buy_call_row["strike"])
    buy_call_premium = _get_premium(buy_call_row)

    # Sell OTM put
    sell_put_row = _find_strike_near(puts_df, lower_target, direction="below")
    if sell_put_row is None:
        return None
    sell_put_strike = float(sell_put_row["strike"])
    sell_put_premium = _get_premium(sell_put_row)

    # Buy put 1 strike wider
    wider_puts = puts_df[puts_df["strike"] < sell_put_strike].sort_values("strike", ascending=False)
    if wider_puts.empty:
        return None
    buy_put_row = wider_puts.iloc[0]
    buy_put_strike = float(buy_put_row["strike"])
    buy_put_premium = _get_premium(buy_put_row)

    if any(p is None for p in [sell_call_premium, buy_call_premium,
                                sell_put_premium, buy_put_premium]):
        return None

    net_credit = (sell_call_premium + sell_put_premium) - (buy_call_premium + buy_put_premium)
    if net_credit <= 0:
        return None

    call_width = buy_call_strike - sell_call_strike
    put_width = sell_put_strike - buy_put_strike
    max_wing_width = max(call_width, put_width)

    max_profit = round(net_credit * 100, 2)
    max_loss = round((max_wing_width - net_credit) * 100, 2)
    be_upper = round(sell_call_strike + net_credit, 2)
    be_lower = round(sell_put_strike - net_credit, 2)

    legs = [
        {"action": "SELL", "type": "put", "strike": sell_put_strike,
         "premium": sell_put_premium, "expiry": expiry},
        {"action": "BUY", "type": "put", "strike": buy_put_strike,
         "premium": buy_put_premium, "expiry": expiry},
        {"action": "SELL", "type": "call", "strike": sell_call_strike,
         "premium": sell_call_premium, "expiry": expiry},
        {"action": "BUY", "type": "call", "strike": buy_call_strike,
         "premium": buy_call_premium, "expiry": expiry},
    ]

    return {
        "legs": legs,
        "risk_profile": {
            "max_profit": max_profit,
            "max_loss": max_loss,
            "breakeven": f"${be_lower} / ${be_upper}",
            "risk_reward_ratio": round(max_profit / max_loss, 2) if max_loss > 0 else None,
            "net_credit": round(net_credit, 2),
        },
    }


def _build_protective_put(ta, options_data, calls_df, puts_df, expiry):
    """Protective put: buy put 5-10% OTM."""
    price = ta.get("price")
    if puts_df is None or puts_df.empty or price is None:
        return None

    # Target 5% OTM
    target = price * 0.95
    buy_row = _find_strike_near(puts_df, target, direction="below")
    if buy_row is None:
        return None

    buy_strike = float(buy_row["strike"])
    buy_premium = _get_premium(buy_row)
    if buy_premium is None:
        return None

    legs = [
        {"action": "BUY", "type": "put", "strike": buy_strike,
         "premium": buy_premium, "expiry": expiry},
    ]

    # Protection kicks in below strike
    max_loss_per_share = (price - buy_strike) + buy_premium  # gap + premium cost
    breakeven = round(price + buy_premium, 2)  # need stock to rise by premium to break even

    return {
        "legs": legs,
        "risk_profile": {
            "max_profit": None,  # unlimited upside minus premium
            "max_loss": round(max_loss_per_share * 100, 2),
            "breakeven": breakeven,
            "risk_reward_ratio": None,
            "protection_level": buy_strike,
            "cost": round(buy_premium * 100, 2),
        },
    }


def _build_long_straddle(ta, options_data, calls_df, puts_df, expiry):
    """Long straddle: buy ATM call + ATM put."""
    price = ta.get("price")
    if (calls_df is None or puts_df is None or calls_df.empty or puts_df.empty
            or price is None):
        return None

    # ATM call
    call_row = _find_strike_near(calls_df, price)
    if call_row is None:
        return None
    call_strike = float(call_row["strike"])
    call_premium = _get_premium(call_row)

    # ATM put (same strike ideally)
    put_row = _find_strike_near(puts_df, call_strike)
    if put_row is None:
        return None
    put_strike = float(put_row["strike"])
    put_premium = _get_premium(put_row)

    if call_premium is None or put_premium is None:
        return None

    total_premium = call_premium + put_premium
    be_upper = round(call_strike + total_premium, 2)
    be_lower = round(put_strike - total_premium, 2)

    legs = [
        {"action": "BUY", "type": "call", "strike": call_strike,
         "premium": call_premium, "expiry": expiry},
        {"action": "BUY", "type": "put", "strike": put_strike,
         "premium": put_premium, "expiry": expiry},
    ]

    return {
        "legs": legs,
        "risk_profile": {
            "max_profit": None,  # unlimited
            "max_loss": round(total_premium * 100, 2),
            "breakeven": f"${be_lower} / ${be_upper}",
            "risk_reward_ratio": None,
            "total_premium": round(total_premium, 2),
            "move_needed_pct": round(total_premium / price * 100, 1),
        },
    }


# Strategy builder dispatch
_BUILDERS = {
    "COVERED_CALL": _build_covered_call,
    "CASH_SECURED_PUT": _build_cash_secured_put,
    "BULL_CALL_SPREAD": _build_bull_call_spread,
    "BEAR_CALL_SPREAD": _build_bear_call_spread,
    "IRON_CONDOR": _build_iron_condor,
    "PROTECTIVE_PUT": _build_protective_put,
    "LONG_STRADDLE": _build_long_straddle,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def recommend_strategies(options_data, ta, fa, chain_calls=None, chain_puts=None):
    """Evaluate all 7 strategies and return ranked recommendations.

    Args:
        options_data: dict from get_options_data()
        ta: dict from get_technical_indicators()
        fa: dict from get_fundamentals()
        chain_calls: DataFrame of call options chain (optional)
        chain_puts: DataFrame of put options chain (optional)

    Returns:
        list of strategy recommendation dicts, sorted by confidence (desc)
    """
    if not ta or ta.get("error"):
        logging.warning("Cannot recommend strategies: technical data unavailable")
        return []

    if not options_data or options_data.get("error"):
        logging.warning("Cannot recommend strategies: options data unavailable")
        return []

    # Get strategy evaluation data
    strat = None
    try:
        from strategy import evaluate_strategy
        strat = evaluate_strategy(ta.get("ticker", ""))
    except Exception:
        strat = {}

    expiry = options_data.get("expiry", "")
    results = []

    for strategy_name in STRATEGY_CONDITIONS:
        try:
            # Evaluate conditions
            condition_results = _evaluate_conditions(strategy_name, ta, fa, options_data, strat)
            score, conditions_met = _score_conditions(condition_results)

            # Count how many conditions are met
            n_met = sum(1 for v in condition_results.values() if v["met"])
            n_total = len(condition_results)

            # Determine status
            if score >= 0.60 and n_met >= 3:
                status = "recommended"
            elif score >= 0.40 and n_met >= 2:
                status = "monitor"
            else:
                status = "avoid"

            # Build legs and risk profile if we have chain data
            trade_details = None
            if chain_calls is not None or chain_puts is not None:
                builder = _BUILDERS.get(strategy_name)
                if builder:
                    try:
                        trade_details = builder(ta, options_data, chain_calls, chain_puts, expiry)
                    except Exception as e:
                        logging.debug(f"Could not build {strategy_name}: {e}")

            rec = {
                "strategy_name": strategy_name,
                "status": status,
                "confidence": score,
                "conditions_met": conditions_met,
                "conditions_summary": f"{n_met}/{n_total}",
                "reasoning": STRATEGY_CONDITIONS[strategy_name]["description"],
                "market_view": STRATEGY_CONDITIONS[strategy_name]["market_view"],
            }

            if trade_details:
                rec["legs"] = trade_details["legs"]
                rec["risk_profile"] = trade_details["risk_profile"]

            results.append(rec)

        except Exception as e:
            logging.error(f"Error evaluating {strategy_name}: {e}")

    # Sort by confidence descending
    results.sort(key=lambda x: x["confidence"], reverse=True)
    return results
