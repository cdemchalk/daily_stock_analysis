import yfinance as yf

def get_fundamentals(ticker):
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar if stock.calendar is not None else {}
        splits = stock.splits

        return {
            "earnings_date": cal.get("Earnings Date", None),
            "dividend_date": cal.get("Ex-Dividend Date", None),
            "stock_split": splits.tail(1).to_dict() if not splits.empty else {}
        }

    except Exception as e:
        print(f"❌ Error fetching fundamentals for {ticker}: {e}")
        return None

