import yfinance as yf
import logging

def get_fundamentals(ticker):
    logging.info(f"Fetching fundamentals for {ticker}")
    try:
        stock = yf.Ticker(ticker)
        cal = stock.calendar if stock.calendar is not None else {}
        splits = stock.splits
        result = {
            "earnings_date": cal.get("Earnings Date", "N/A"),
            "dividend_date": cal.get("Ex-Dividend Date", "N/A"),
            "stock_split": splits.tail(1).to_dict() if not splits.empty else {}
        }
        if all(v == "N/A" or v == {} for v in result.values()):
            logging.warning(f"No fundamental data available for {ticker}")
        return result
    except Exception as e:
        logging.error(f"Error fetching fundamentals for {ticker}: {str(e)}")
        return {"error": f"Fundamentals unavailable: {str(e)}"}