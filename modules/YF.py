import yfinance as yf
import pandas as pd

print("yfinance version:", yf.__version__)
print("pandas version:", pd.__version__)

try:
    df = yf.download('AAPL', period='5d', interval='1d')
    print("\n✅ Download complete.")
    print(df)
except Exception as e:
    print("\n❌ Exception occurred:")
    print(repr(e))