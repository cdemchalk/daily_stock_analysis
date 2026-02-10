import logging


def _fmt(v, nd=2, default="–"):
    try:
        if v is None:
            return default
        if v != v:  # NaN
            return default
        if isinstance(v, bool):
            return "Yes" if v else "No"
        if isinstance(v, (int, float)):
            return f"{v:.{nd}f}"
        return str(v)
    except Exception:
        return default


def _fmt_large(v, default="–"):
    """Format large numbers as $1.2B / $45.3M."""
    try:
        if v is None or v != v:
            return default
        v = float(v)
        if abs(v) >= 1e12:
            return f"${v/1e12:.1f}T"
        if abs(v) >= 1e9:
            return f"${v/1e9:.1f}B"
        if abs(v) >= 1e6:
            return f"${v/1e6:.1f}M"
        if abs(v) >= 1e3:
            return f"${v/1e3:.1f}K"
        return f"${v:.0f}"
    except Exception:
        return default


def _pct_fmt(v, default="–"):
    """Format percentage values."""
    try:
        if v is None or v != v:
            return default
        return f"{float(v):+.1f}%"
    except Exception:
        return default


def _signal_badge(strat):
    """Return colored signal badge HTML."""
    if not strat or strat.get("error"):
        return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#e0e0e0;color:#666;font-size:11px">N/A</span>'
    if strat.get("entry_signal"):
        return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#c8e6c9;color:#1b5e20;font-weight:600;font-size:11px">BUY SIGNAL</span>'
    if strat.get("exit_signal"):
        return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#ffcdd2;color:#b71c1c;font-weight:600;font-size:11px">EXIT SIGNAL</span>'
    rsi = strat.get("RSI")
    if rsi is not None:
        if rsi > 70:
            return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#fff3e0;color:#e65100;font-size:11px">OVERBOUGHT</span>'
        if rsi < 30:
            return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#e3f2fd;color:#0d47a1;font-size:11px">OVERSOLD</span>'
    return '<span style="display:inline-block;padding:2px 8px;border-radius:4px;background:#f5f5f5;color:#666;font-size:11px">NEUTRAL</span>'


def _rsi_color(rsi_val):
    """Return RSI value with color styling."""
    if rsi_val is None:
        return "–"
    try:
        v = float(rsi_val)
        if v > 70:
            return f'<span style="color:#c62828;font-weight:600">{v:.1f}</span>'
        if v < 30:
            return f'<span style="color:#2e7d32;font-weight:600">{v:.1f}</span>'
        return f"{v:.1f}"
    except Exception:
        return "–"


def _extract_verdict(summary):
    """Extract the Verdict line from GPT summary."""
    if not summary:
        return "–"
    for line in summary.split("\n"):
        if "**Verdict:**" in line:
            return line.replace("**Verdict:**", "").strip()
    return summary[:80] + "..." if len(summary) > 80 else summary


def _sentiment_label(sentiment):
    """Return a short sentiment label."""
    if not sentiment or sentiment.get("error"):
        return "–"
    score = sentiment.get("sentiment_score", 0)
    if score > 0.3:
        return f'<span style="color:#2e7d32">Bull {score:+.2f}</span>'
    if score < -0.3:
        return f'<span style="color:#c62828">Bear {score:+.2f}</span>'
    return f'Mixed {score:+.2f}'


def _key_level(ta):
    """Return the nearest support or resistance."""
    if not ta or ta.get("error"):
        return "–"
    price = ta.get("price")
    support = ta.get("support_20d")
    resistance = ta.get("resistance_20d")
    if price and support and resistance:
        dist_s = abs(price - support)
        dist_r = abs(price - resistance)
        if dist_s < dist_r:
            return f"S: ${support:.2f}"
        return f"R: ${resistance:.2f}"
    return "–"


def _format_summary_html(summary):
    """Convert GPT markdown summary to HTML."""
    if not summary or summary == "No summary available.":
        return "<p>No summary available</p>"
    try:
        parts = summary.split("**")
        html = ""
        for i in range(1, len(parts), 2):
            header = parts[i].strip()
            content = parts[i + 1].strip() if i + 1 < len(parts) else ""
            content = content.replace("\n- ", "<br>&bull; ").replace("\n", "<br>")
            html += f'<p style="margin:4px 0"><strong>{header}</strong> {content}</p>'
        return html if html else f"<p>{summary}</p>"
    except Exception:
        return f"<p>{summary}</p>"


def _options_snapshot_bar(options):
    """Render a compact options data bar."""
    if not options or options.get("error"):
        return ""
    cells = []
    if options.get("expiry"):
        cells.append(f"Exp: {options['expiry']}")
    if options.get("dte") is not None:
        cells.append(f"DTE: {options['dte']}")
    if options.get("atm_iv") is not None:
        cells.append(f"ATM IV: {options['atm_iv']:.1%}")
    if options.get("atm_call_premium") is not None:
        cells.append(f"Call: ${options['atm_call_premium']:.2f}")
    if options.get("atm_put_premium") is not None:
        cells.append(f"Put: ${options['atm_put_premium']:.2f}")
    if options.get("pc_ratio_volume") is not None:
        cells.append(f"P/C Vol: {options['pc_ratio_volume']:.2f}")
    if options.get("max_pain") is not None:
        cells.append(f"Max Pain: ${options['max_pain']:.2f}")
    if not cells:
        return ""
    return (
        '<div style="background:#f8f9fa;border:1px solid #e0e0e0;border-radius:6px;padding:6px 10px;margin:6px 0;font-size:12px;color:#333">'
        f'<strong>Options:</strong> {" &nbsp;|&nbsp; ".join(cells)}'
        '</div>'
    )


def _strategy_card(options_strategies):
    """Render strategy recommendation card."""
    if not options_strategies:
        return ""

    # Find top recommendation
    top = None
    for rec in options_strategies:
        if rec.get("status") == "recommended":
            top = rec
            break
    if top is None:
        top = options_strategies[0]

    status = top.get("status", "avoid")
    confidence = top.get("confidence", 0)
    name = top.get("strategy_name", "").replace("_", " ")

    # Color by status
    if status == "recommended":
        border_color = "#4caf50"
        bg_color = "#e8f5e9"
        status_label = "Recommended"
    elif status == "monitor":
        border_color = "#ff9800"
        bg_color = "#fff8e1"
        status_label = "Monitor"
    else:
        border_color = "#9e9e9e"
        bg_color = "#fafafa"
        status_label = "No Clear Setup"

    # Build legs line
    legs_line = ""
    legs = top.get("legs", [])
    if legs:
        parts = []
        for leg in legs:
            parts.append(f"{leg['action']} {leg['strike']}{leg['type'][0].upper()} @ ${leg['premium']:.2f}")
        exp_str = legs[0].get("expiry", "")
        if exp_str:
            # Format expiry as M/D
            try:
                from datetime import datetime
                exp_dt = datetime.strptime(exp_str, "%Y-%m-%d")
                exp_str = exp_dt.strftime("%-m/%-d")
            except Exception:
                pass
        legs_line = f"{' &nbsp;|&nbsp; '.join(parts)} &nbsp;|&nbsp; Exp {exp_str}"

    # Build risk line
    risk_line = ""
    rp = top.get("risk_profile", {})
    if rp:
        risk_parts = []
        if rp.get("max_profit") is not None:
            risk_parts.append(f"Max Profit: ${rp['max_profit']:,.0f}")
        if rp.get("max_loss") is not None:
            risk_parts.append(f"Max Loss: ${rp['max_loss']:,.0f}")
        if rp.get("breakeven") is not None:
            be = rp["breakeven"]
            if isinstance(be, (int, float)):
                risk_parts.append(f"B/E: ${be:.2f}")
            else:
                risk_parts.append(f"B/E: {be}")
        if rp.get("risk_reward_ratio") is not None:
            risk_parts.append(f"R/R: {rp['risk_reward_ratio']}x")
        risk_line = " &nbsp;|&nbsp; ".join(risk_parts)

    html = f'<div style="background:{bg_color};border:1px solid {border_color};border-left:4px solid {border_color};border-radius:6px;padding:8px 12px;margin:6px 0;font-size:12px">'
    html += f'<div style="font-weight:600;margin-bottom:4px">{status_label}: {name} ({confidence:.0%} confidence)</div>'
    if legs_line:
        html += f'<div style="color:#333">{legs_line}</div>'
    if risk_line:
        html += f'<div style="color:#555;margin-top:2px">{risk_line}</div>'
    html += '</div>'
    return html


def _backtest_card(backtest):
    """Render backtest results card."""
    if not backtest:
        return ""

    parts = []

    strat_bt = backtest.get("strategy")
    if strat_bt and not strat_bt.get("error"):
        name = strat_bt.get("strategy", "Strategy").replace("_", " ")
        total = strat_bt.get("total_signals", 0)
        trades = strat_bt.get("trades_taken", 0)
        wr = strat_bt.get("win_rate", 0)
        avg_ret = strat_bt.get("avg_return_pct", 0)
        max_dd = strat_bt.get("max_drawdown_pct", 0)
        pf = strat_bt.get("profit_factor", 0)
        parts.append(
            f'<div style="margin-bottom:4px"><strong>{name}</strong> (12mo, BS simulated) '
            f'Signals: {total} | Trades: {trades} | Win Rate: {wr:.1%} | '
            f'Avg Return: {avg_ret:+.1f}% | Max DD: {max_dd:.1f}% | PF: {pf:.1f}x</div>'
        )

    ee_bt = backtest.get("entry_exit")
    if ee_bt and not ee_bt.get("error"):
        trades = ee_bt.get("trades_taken", 0)
        wr = ee_bt.get("win_rate", 0)
        avg_ret = ee_bt.get("avg_return_pct", 0)
        parts.append(
            f'<div>Entry/Exit Signals: {trades} trades | Win Rate: {wr:.1%} | '
            f'Avg Return: {avg_ret:+.1f}%</div>'
        )

    if not parts:
        return ""

    return (
        '<div style="background:#f3e5f5;border:1px solid #ce93d8;border-left:4px solid #ab47bc;'
        'border-radius:6px;padding:8px 12px;margin:6px 0;font-size:12px">'
        '<div style="font-weight:600;margin-bottom:4px">Backtest Results</div>'
        + "".join(parts) +
        '<div style="color:#888;font-size:10px;margin-top:4px">Simulated via Black-Scholes (estimated premiums)</div>'
        '</div>'
    )


def _catalyst_calendar(summaries):
    """Build a catalyst calendar table from all tickers' fundamentals."""
    events = []
    for tkr, p in summaries.items():
        fa = p.get("fundamentals") or {}
        if fa.get("error"):
            continue
        ed = fa.get("earnings_date")
        dte = fa.get("days_to_earnings")
        if ed and ed != "N/A":
            events.append({"ticker": tkr, "event": "Earnings", "date": str(ed), "days": dte})
        dd = fa.get("dividend_date")
        dtd = fa.get("days_to_dividend")
        if dd and dd != "N/A":
            events.append({"ticker": tkr, "event": "Ex-Dividend", "date": str(dd), "days": dtd})

    if not events:
        return ""

    events.sort(key=lambda x: x.get("days") or 999)
    rows = ""
    for e in events:
        days_str = f'{e["days"]}d' if e["days"] is not None else "–"
        rows += f'<tr><td style="padding:3px 8px">{e["ticker"]}</td><td style="padding:3px 8px">{e["event"]}</td><td style="padding:3px 8px">{e["date"]}</td><td style="padding:3px 8px">{days_str}</td></tr>'

    return f"""
    <div style="margin:16px 0">
      <h3 style="margin:0 0 6px 0;font-size:15px">Catalyst Calendar</h3>
      <table style="border-collapse:collapse;font-size:12px;width:100%">
        <thead><tr style="background:#f0f0f0">
          <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #ddd">Ticker</th>
          <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #ddd">Event</th>
          <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #ddd">Date</th>
          <th style="padding:4px 8px;text-align:left;border-bottom:1px solid #ddd">Days</th>
        </tr></thead>
        <tbody>{rows}</tbody>
      </table>
    </div>
    """


def build_html_report(summaries, run_timestamp=None, **kwargs):
    try:
        # Header
        html = f"""<html><body style="font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;color:#111;max-width:800px;margin:0 auto;padding:12px">
        <h2 style="margin:0">Daily Stock Analysis</h2>
        <div style="color:#666;margin-bottom:12px;font-size:12px">Generated: {run_timestamp}</div>
        <hr style="border:none;border-top:1px solid #ddd;margin:8px 0 16px"/>
        """

        # Dashboard table
        dash_rows = ""
        for tkr, p in summaries.items():
            ta = p.get("technical") or {}
            strat = p.get("strategy") or {}
            options = p.get("options") or {}
            sentiment = p.get("sentiment") or {}
            summary = p.get("summary", "")

            price = _fmt(ta.get("price"))
            pct_1d = _pct_fmt(ta.get("pct_change_1d"))
            signal = _signal_badge(strat)
            rsi = _rsi_color(ta.get("RSI"))
            atm_iv = f"{options.get('atm_iv'):.1%}" if options.get("atm_iv") else "–"
            key_lvl = _key_level(ta)
            sent = _sentiment_label(sentiment)
            verdict = _extract_verdict(summary)

            dash_rows += f"""<tr style="border-bottom:1px solid #eee">
              <td style="padding:6px 8px;font-weight:600">{tkr}</td>
              <td style="padding:6px 8px">${price}</td>
              <td style="padding:6px 8px">{pct_1d}</td>
              <td style="padding:6px 8px">{signal}</td>
              <td style="padding:6px 8px">{rsi}</td>
              <td style="padding:6px 8px">{atm_iv}</td>
              <td style="padding:6px 8px;font-size:12px">{key_lvl}</td>
              <td style="padding:6px 8px;font-size:12px">{sent}</td>
              <td style="padding:6px 8px;font-size:11px;max-width:200px">{verdict[:60]}</td>
            </tr>"""

        html += f"""
        <table style="border-collapse:collapse;width:100%;font-size:13px;margin-bottom:16px">
          <thead><tr style="background:#f5f5f5;border-bottom:2px solid #ddd">
            <th style="padding:6px 8px;text-align:left">Ticker</th>
            <th style="padding:6px 8px;text-align:left">Price</th>
            <th style="padding:6px 8px;text-align:left">1D%</th>
            <th style="padding:6px 8px;text-align:left">Signal</th>
            <th style="padding:6px 8px;text-align:left">RSI</th>
            <th style="padding:6px 8px;text-align:left">ATM IV</th>
            <th style="padding:6px 8px;text-align:left">Key Level</th>
            <th style="padding:6px 8px;text-align:left">Sent.</th>
            <th style="padding:6px 8px;text-align:left">Verdict</th>
          </tr></thead>
          <tbody>{dash_rows}</tbody>
        </table>
        """

        # Per-ticker detail sections
        for tkr, p in summaries.items():
            summary = p.get("summary") or "No summary available."
            ta = p.get("technical") or {}
            fa = p.get("fundamentals") or {}
            options = p.get("options") or {}
            strat = p.get("strategy") or {}
            opts_strats = p.get("options_strategies")
            bt = p.get("backtest")

            summary_html = _format_summary_html(summary)
            options_bar = _options_snapshot_bar(options)
            strategy_html = _strategy_card(opts_strats)
            backtest_html = _backtest_card(bt)

            # Compact technicals line
            tech_items = []
            if ta.get("SMA_50"):
                tech_items.append(f"SMA50: {_fmt(ta['SMA_50'])}")
            if ta.get("SMA_200"):
                tech_items.append(f"SMA200: {_fmt(ta['SMA_200'])}")
            if ta.get("VWAP"):
                tech_items.append(f"VWAP: {_fmt(ta['VWAP'])}")
            if ta.get("MACD_histogram") is not None:
                tech_items.append(f"MACD Hist: {_fmt(ta['MACD_histogram'], 3)}")
            if ta.get("BB_width") is not None:
                squeeze = " (SQUEEZE)" if ta["BB_width"] < 0.04 else ""
                tech_items.append(f"BB Width: {_fmt(ta['BB_width'], 3)}{squeeze}")
            if ta.get("volume_ratio") is not None:
                tech_items.append(f"Vol Ratio: {_fmt(ta['volume_ratio'], 1)}x")
            tech_line = " &nbsp;|&nbsp; ".join(tech_items) if tech_items else "–"

            # Fundamentals line
            fund_items = []
            if fa.get("marketCap"):
                fund_items.append(f"MCap: {_fmt_large(fa['marketCap'])}")
            if fa.get("trailingPE"):
                fund_items.append(f"P/E: {_fmt(fa['trailingPE'], 1)}")
            if fa.get("recommendationKey"):
                fund_items.append(f"Rec: {fa['recommendationKey'].upper()}")
            if fa.get("targetMeanPrice"):
                fund_items.append(f"Target: ${_fmt(fa['targetMeanPrice'])}")
            if fa.get("shortPercentOfFloat"):
                fund_items.append(f"Short: {float(fa['shortPercentOfFloat'])*100:.1f}%")
            fund_line = " &nbsp;|&nbsp; ".join(fund_items) if fund_items else "–"

            html += f"""
            <section style="margin:0 0 16px 0;padding:10px 12px;border:1px solid #e0e0e0;border-radius:8px">
              <h3 style="margin:0 0 6px 0;font-size:16px">{tkr}</h3>
              {summary_html}
              {options_bar}
              {strategy_html}
              {backtest_html}
              <div style="font-size:12px;color:#555;margin:4px 0"><strong>Technicals:</strong> {tech_line}</div>
              <div style="font-size:12px;color:#555;margin:4px 0"><strong>Fundamentals:</strong> {fund_line}</div>
            </section>
            """

        # Catalyst Calendar
        html += _catalyst_calendar(summaries)

        html += "</body></html>"
        logging.info("HTML report generated successfully")
        return html
    except Exception as e:
        logging.error(f"Error generating HTML report: {str(e)}")
        return "<html><body><h2>Daily Stock Analysis</h2><p>Error generating report</p></body></html>"
