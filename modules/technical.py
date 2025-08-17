import yfinance as yf
import pandas as pd
import logging

def compute_rsi(close: pd.Series, period=14):
    delta = close.diff()
    gain = delta.clip(lower=0)
    loss = -delta.clip(upper=0)
    avg_gain = gain.rolling(period).mean()
    avg_loss = loss.rolling(period).mean()
    rs = avg_gain / avg_loss
    return 100 - (100 / (1 + rs))

def get_technical_indicators(ticker):
    logging.info(f"Fetching technicals for {ticker}")
    try:
        data = yf.download(ticker, period="6mo", interval="1d", auto_adjust=True)
        if data.empty:
            logging.warning(f"No data from yf.download for {ticker}, trying auto_adjust=False")
            data = yf.download(ticker, period="6mo", interval="1d", auto_adjust=False)
        if data.empty:
            logging.error(f"No data for {ticker}")
            return {"error": f"No data for {ticker}"}
        data["EMA_9"]  = data["Close"].ewm(span=9, adjust=False).mean()
        data["EMA_20"] = data["Close"].ewm(span=20, adjust=False).mean()
        data["RSI"]    = compute_rsi(data["Close"], 14)
        data["VWAP"]   = (data["Close"]*data["Volume"]).cumsum() / data["Volume"].cumsum()
        last = data.dropna().iloc[-1]
        return {
            "price": float(last["Close"]),
            "EMA_9": float(last["EMA_9"]),
            "EMA_20": float(last["EMA_20"]),
            "RSI": float(last["RSI"]),
            "VWAP": float(last["VWAP"]),
        }
    except Exception as e:
        logging.error(f"Error fetching technicals for {ticker}: {str(e)}")
        return {"error": f"Technicals unavailable: {str(e)}"}