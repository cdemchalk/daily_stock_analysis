import yfinance as yf
import logging
from datetime import datetime, timezone


def get_fundamentals(ticker):
    logging.info(f"Fetching fundamentals for {ticker}")
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar if stock.calendar is not None else {}
        splits = stock.splits
        info = stock.info or {}

        # Calendar dates
        earnings_date_raw = cal.get("Earnings Date", "N/A")
        dividend_date_raw = cal.get("Ex-Dividend Date", "N/A")
        stock_split = splits.tail(1).to_dict() if not splits.empty else {}

        def _extract_date(val):
            """Extract a single date from various yfinance return formats."""
            if val is None or val == "N/A":
                return None
            # yfinance sometimes returns a list of dates
            if isinstance(val, (list, tuple)) and len(val) > 0:
                val = val[0]
            if hasattr(val, 'date'):
                return val.date() if callable(getattr(val, 'date', None)) else val
            if isinstance(val, str):
                try:
                    return datetime.strptime(val, "%Y-%m-%d").date()
                except ValueError:
                    pass
            return val if hasattr(val, 'year') else None

        earnings_date_obj = _extract_date(earnings_date_raw)
        dividend_date_obj = _extract_date(dividend_date_raw)

        earnings_date = str(earnings_date_obj) if earnings_date_obj else "N/A"
        dividend_date = str(dividend_date_obj) if dividend_date_obj else "N/A"

        # Compute days_to_earnings
        days_to_earnings = None
        if earnings_date_obj:
            try:
                days_to_earnings = (earnings_date_obj - datetime.now(timezone.utc).date()).days
            except Exception:
                pass

        # Compute days_to_dividend
        days_to_dividend = None
        if dividend_date_obj:
            try:
                days_to_dividend = (dividend_date_obj - datetime.now(timezone.utc).date()).days
            except Exception:
                pass

        # Extract last earnings date from earnings_dates (for anchored VWAP)
        last_earnings_date = None
        try:
            ed_df = stock.earnings_dates
            if ed_df is not None and not ed_df.empty:
                now = datetime.now(timezone.utc)
                past = ed_df[ed_df.index <= now]
                if not past.empty:
                    last_earnings_date = str(past.index[0].date())
        except Exception:
            pass

        def _safe_get(key, default=None):
            v = info.get(key, default)
            return v if v is not None else default

        result = {
            "earnings_date": earnings_date,
            "dividend_date": dividend_date,
            "stock_split": stock_split,
            "days_to_earnings": days_to_earnings,
            "days_to_dividend": days_to_dividend,
            "last_earnings_date": last_earnings_date,
            # Valuation
            "trailingPE": _safe_get("trailingPE"),
            "forwardPE": _safe_get("forwardPE"),
            "marketCap": _safe_get("marketCap"),
            # Growth
            "revenueGrowth": _safe_get("revenueGrowth"),
            "earningsGrowth": _safe_get("earningsGrowth"),
            "profitMargins": _safe_get("profitMargins"),
            # Analyst
            "targetMeanPrice": _safe_get("targetMeanPrice"),
            "targetHighPrice": _safe_get("targetHighPrice"),
            "targetLowPrice": _safe_get("targetLowPrice"),
            "recommendationKey": _safe_get("recommendationKey"),
            "numberOfAnalystOpinions": _safe_get("numberOfAnalystOpinions"),
            # Short interest
            "shortPercentOfFloat": _safe_get("shortPercentOfFloat"),
            # Institutional
            "heldPercentInstitutions": _safe_get("heldPercentInstitutions"),
            # Classification
            "sector": _safe_get("sector"),
            "industry": _safe_get("industry"),
            # Range context
            "fiftyTwoWeekHigh": _safe_get("fiftyTwoWeekHigh"),
            "fiftyTwoWeekLow": _safe_get("fiftyTwoWeekLow"),
            # Income
            "dividendYield": _safe_get("dividendYield"),
        }

        return result
    except Exception as e:
        logging.error(f"Error fetching fundamentals for {ticker}: {str(e)}")
        return {"error": f"Fundamentals unavailable: {str(e)}"}
