#!/usr/bin/env python3
# -*- coding: utf-8 -*-

from openai import OpenAI
import os

SYSTEM_PROMPT = """You are an experienced derivatives trader and portfolio analyst with two analysis lenses:

1. **Buy & Hold Lens:** Evaluate fundamental thesis, valuation relative to peers, catalyst timeline, and long-term positioning.
2. **Rhythmic/Swing Lens:** Identify pattern setups, key levels, entry/stop/target zones, and momentum signals.

You produce concise, actionable analysis. Never pad with generic financial disclaimers. Every sentence must deliver specific, data-backed insight.

OUTPUT FORMAT — You must produce exactly these sections:

**Verdict:** [One-line bull/bear/neutral call with conviction level]
**Buy & Hold Lens:** [2-3 bullets on fundamental thesis and valuation]
**Swing/Rhythmic Setup:** Entry: $X | Stop: $X | Target: $X [+ 1-2 bullets on pattern/momentum]
**Options Play:** [Use the pre-computed OPTIONS STRATEGY RECOMMENDATION below if provided — do NOT invent your own strategy. Include the exact strikes, premiums, and risk/reward numbers from the recommendation. If no recommendation is provided, suggest a strategy based on the options data.]
**What Changed Today:** [1-2 bullets on most significant daily developments]
**Risk Flag:** [One line on the biggest risk; omit if nothing notable]

Keep total output under 300 words. Be precise with numbers."""


def _format_input(ticker, ta, fa, news, options=None, sentiment=None, strategy=None, options_strategies=None):
    """Convert raw data dicts into clean labeled text for GPT."""
    sections = []

    sections.append(f"TICKER: {ticker}")

    if ta and not ta.get("error"):
        lines = []
        for key in ["price", "RSI", "VWAP", "VWAP_anchor", "EMA_9", "EMA_20",
                     "MACD_line", "MACD_signal", "MACD_histogram",
                     "BB_upper", "BB_lower", "BB_width",
                     "SMA_50", "SMA_200", "volume_ratio",
                     "support_20d", "resistance_20d",
                     "week_52_high", "week_52_low",
                     "pct_change_1d", "pct_change_5d", "pct_change_1mo", "pct_change_3mo"]:
            v = ta.get(key)
            if v is not None:
                if isinstance(v, float):
                    lines.append(f"  {key}: {v:.4f}" if abs(v) < 1 else f"  {key}: {v:.2f}")
                else:
                    lines.append(f"  {key}: {v}")
        sections.append("TECHNICALS:\n" + "\n".join(lines))

    if fa and not fa.get("error"):
        lines = []
        for key in ["trailingPE", "forwardPE", "marketCap", "revenueGrowth", "earningsGrowth",
                     "profitMargins", "targetMeanPrice", "targetHighPrice", "targetLowPrice",
                     "recommendationKey", "numberOfAnalystOpinions", "shortPercentOfFloat",
                     "heldPercentInstitutions", "sector", "industry", "dividendYield",
                     "days_to_earnings", "days_to_dividend", "earnings_date", "dividend_date"]:
            v = fa.get(key)
            if v is not None and v != "N/A":
                lines.append(f"  {key}: {v}")
        sections.append("FUNDAMENTALS:\n" + "\n".join(lines))

    if options and not options.get("error"):
        lines = []
        for key in ["expiry", "dte", "atm_strike", "atm_iv", "atm_call_premium", "atm_put_premium",
                     "atm_call_pct", "atm_put_pct", "pc_ratio_volume", "pc_ratio_oi",
                     "max_pain", "skew"]:
            v = options.get(key)
            if v is not None:
                lines.append(f"  {key}: {v}")
        unusual = options.get("unusual_activity", [])
        if unusual:
            lines.append(f"  unusual_activity: {len(unusual)} strikes with vol>2x OI")
            for u in unusual[:3]:
                lines.append(f"    {u['type']} {u['strike']}: vol={u['volume']} oi={u['openInterest']} ratio={u['ratio']}x")
        sections.append("OPTIONS:\n" + "\n".join(lines))

    if sentiment and not sentiment.get("error"):
        lines = [
            f"  source: {sentiment.get('source', 'unknown')}",
            f"  sentiment_score: {sentiment.get('sentiment_score', 0)} (-1=bearish, +1=bullish)",
            f"  bullish: {sentiment.get('bullish_count', 0)}, bearish: {sentiment.get('bearish_count', 0)}, total: {sentiment.get('total_messages', 0)}",
        ]
        snippets = sentiment.get("snippets", [])
        if snippets:
            lines.append("  top snippets:")
            for s in snippets[:3]:
                lines.append(f"    [{s.get('sentiment', '?')}] {s.get('text', '')[:100]}")
        sections.append("SENTIMENT:\n" + "\n".join(lines))

    if strategy and not strategy.get("error"):
        lines = [
            f"  entry_signal: {strategy.get('entry_signal', False)}",
            f"  exit_signal: {strategy.get('exit_signal', False)}",
        ]
        reasons = strategy.get("reasons", {})
        if reasons.get("entry"):
            lines.append("  entry_reasons: " + ", ".join(f"{k}={v}" for k, v in reasons["entry"].items()))
        if reasons.get("exit"):
            lines.append("  exit_reasons: " + ", ".join(f"{k}={v}" for k, v in reasons["exit"].items()))
        sections.append("STRATEGY:\n" + "\n".join(lines))

    if options_strategies:
        # Find top recommended strategy
        top_rec = None
        for rec in options_strategies:
            if rec.get("status") == "recommended":
                top_rec = rec
                break
        if top_rec is None and options_strategies:
            top_rec = options_strategies[0]

        if top_rec:
            lines = [
                f"  Top strategy: {top_rec['strategy_name']} (confidence: {top_rec['confidence']:.0%})",
                f"  Status: {top_rec['status']}",
            ]
            legs = top_rec.get("legs", [])
            if legs:
                leg_strs = []
                for leg in legs:
                    leg_strs.append(f"{leg['action']} {leg['strike']}{leg['type'][0].upper()} @ ${leg['premium']:.2f}")
                lines.append(f"  Legs: {', '.join(leg_strs)} (Exp {legs[0].get('expiry', 'N/A')})")

            rp = top_rec.get("risk_profile", {})
            if rp:
                if rp.get("max_profit") is not None:
                    lines.append(f"  Max Profit: ${rp['max_profit']:.0f}")
                if rp.get("max_loss") is not None:
                    lines.append(f"  Max Loss: ${rp['max_loss']:.0f}")
                if rp.get("breakeven") is not None:
                    lines.append(f"  Breakeven: {rp['breakeven']}")
                if rp.get("risk_reward_ratio") is not None:
                    lines.append(f"  Risk/Reward: {rp['risk_reward_ratio']}x")

            conditions = top_rec.get("conditions_met", [])
            if conditions:
                lines.append(f"  Conditions: {', '.join(conditions)}")

            sections.append("OPTIONS STRATEGY RECOMMENDATION:\n" + "\n".join(lines))

    if news:
        titles = [n.get("title", "") for n in news[:5] if n.get("title")]
        if titles:
            sections.append("NEWS:\n" + "\n".join(f"  - {t}" for t in titles))

    return "\n\n".join(sections)


def summarize_insights(ticker, ta, fa, news, options=None, sentiment=None, strategy=None, options_strategies=None):
    client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))
    user_content = _format_input(ticker, ta, fa, news, options, sentiment, strategy, options_strategies)
    resp = client.chat.completions.create(
        model="gpt-5",
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
        max_completion_tokens=16000,
    )
    return resp.choices[0].message.content.strip()
