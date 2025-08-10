def _fmt(v, nd=2, default="–"):
    try:
        if v is None: 
            return default
        # handle nan-like
        if v != v:
            return default
        if isinstance(v, bool):
            return "✔" if v else "✖"
        if isinstance(v, (int, float)):
            return f"{v:.{nd}f}"
        return str(v)
    except Exception:
        return default

def _badge(text, color="#444", bg="#eee"):
    return f"<span style='display:inline-block;padding:2px 6px;border-radius:6px;background:{bg};color:{color};font:12px/1.4 sans-serif'>{text}</span>"

def build_html_report(summaries, run_timestamp=None, **kwargs):
    head = f"""
      <h2 style="margin:0">Daily Stock Report</h2>
      <div style="color:#666;margin-bottom:12px">Generated: {run_timestamp}</div>
      <hr style="border:none;border-top:1px solid #ddd;margin:8px 0 16px"/>
    """
    blocks = []

    for tkr, p in summaries.items():
        summary = p.get("summary") or "No summary available."
        strat = p.get("strategy") or {}
        social = p.get("social") or {}
        ta     = p.get("technical") or {}
        err    = strat.get("error")

        # Strategy row (show error if present)
        if err:
            strat_line = f"{_badge('strategy error', '#b00', '#fde')}: {err}"
        else:
            strat_line = (
                f"entry={_fmt(strat.get('entry_signal'))} "
                f"exit={_fmt(strat.get('exit_signal'))} "
                f"ATR14={_fmt(strat.get('ATR_14'))}"
            )

        # Technical snapshot (nice to have)
        tech_line = (
            f"Price={_fmt(ta.get('price'))}  "
            f"RSI={_fmt(ta.get('RSI'))}  "
            f"VWAP={_fmt(ta.get('VWAP'))}  "
            f"EMA9={_fmt(ta.get('EMA_9'))}  "
            f"EMA20={_fmt(ta.get('EMA_20'))}"
        )

        # Social snapshot with badges
        hype   = bool(social.get("hype_spike")) if social else False
        hype_b = _badge("Hype Spike", "#fff", "#b00") if hype else _badge("No Hype", "#054", "#def")
        bear   = bool(social.get("bearish_pressure")) if social else False
        bear_b = _badge("Bearish Pressure", "#fff", "#b00") if bear else _badge("Neutral/Pos", "#054", "#def")

        social_line = (
            f"mph={_fmt(social.get('mentions_per_hour'))}  "
            f"z_mph={_fmt(social.get('z_mph'))}  "
            f"avg_sent={_fmt(social.get('avg_sentiment'), 3)}  "
            f"pos%={_fmt(social.get('pos_share'), 3)}  "
            f"neg%={_fmt(social.get('neg_share'), 3)}  "
            f"{hype_b} {bear_b}"
        )

        # Compact keyword flags (only show those >0)
        kf = social.get("keyword_flags") or {}
        kf_present = ", ".join([f"{k}:{v}" for k, v in kf.items() if v])
        if kf_present:
            kf_line = f"<div style='color:#555;margin-top:4px'>Keywords: {kf_present}</div>"
        else:
            kf_line = ""

        block = f"""
        <section style="margin:0 0 18px 0;padding:10px 12px;border:1px solid #eee;border-radius:10px">
          <h3 style="margin:0 0 8px 0">{tkr}</h3>
          <div style="margin:6px 0 10px 0"><b>Summary:</b><br/>{summary}</div>
          <div style="margin:6px 0"><b>Signals:</b> {strat_line}</div>
          <div style="margin:6px 0"><b>Technicals:</b> {tech_line}</div>
          <div style="margin:6px 0"><b>Social:</b> {social_line}{kf_line}</div>
        </section>
        """
        blocks.append(block)

    html = f"<html><body style='font-family:system-ui,Segoe UI,Roboto,Arial,sans-serif;font-size:14px;color:#111'>{head}{''.join(blocks)}</body></html>"
    return html