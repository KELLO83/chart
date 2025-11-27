import yfinance as yf
import pandas as pd
import json
import logging
from typing import Dict, Any

# Mock logging
logging.basicConfig(level=logging.DEBUG)

def get_nasdaq_ohlcv(
    ticker: str,
    period: str = "1mo",
    interval: str = "1d"
) -> Dict[str, Any]:
    """Retrieves OHLCV data for a US stock as a JSON dictionary."""
    try:
        logging.debug(f"Retrieving NASDAQ OHLCV: {ticker}, period={period}, interval={interval}")
        
        df = yf.download(ticker, period=period, interval=interval, progress=False)
        
        if df.empty:
            return {"error": f"No data found for {ticker}"}

        # Flatten MultiIndex columns if present
        if isinstance(df.columns, pd.MultiIndex):
            df.columns = df.columns.get_level_values(0)

        # Rename columns
        df = df.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })

        # Ensure required columns
        required_cols = ["open", "high", "low", "close", "volume"]
        available_cols = [c for c in required_cols if c in df.columns]
        df = df[available_cols].dropna()

        # Convert to dict with date as key
        result = {}
        for date, row in df.iterrows():
            date_str = date.strftime("%Y-%m-%d")
            result[date_str] = row.to_dict()
            
        # Sort by date descending
        sorted_result = dict(sorted(result.items(), key=lambda item: item[0], reverse=True))
        
        return sorted_result

    except Exception as e:
        error_message = f"Failed to retrieve NASDAQ OHLCV: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


def get_nasdaq_fundamental(ticker: str) -> Dict[str, Any]:
    """Retrieves fundamental data for a US stock."""
    try:
        logging.debug(f"Retrieving NASDAQ fundamentals: {ticker}")
        
        ticker_obj = yf.Ticker(ticker)
        info = ticker_obj.info
        
        keys = [
            "shortName", "longName", "sector", "industry", "currency",
            "marketCap", "enterpriseValue", "trailingPE", "forwardPE",
            "pegRatio", "priceToBook", "dividendYield", "fiftyTwoWeekHigh",
            "fiftyTwoWeekLow", "longBusinessSummary"
        ]
        
        result = {k: info.get(k) for k in keys if k in info}
        return result

    except Exception as e:
        error_message = f"Failed to retrieve NASDAQ fundamentals: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}

if __name__ == "__main__":
    print("--- Testing get_nasdaq_fundamental('AAPL') ---")
    fund = get_nasdaq_fundamental("AAPL")
    if "error" in fund:
        print("Error:", fund["error"])
    else:
        print("Market Cap:", fund.get("marketCap"))
        print("Sector:", fund.get("sector"))
        # print("Summary:", fund.get("longBusinessSummary")[:50] + "...")

    print("\n--- Testing get_nasdaq_ohlcv('AAPL', period='5d') ---")
    ohlcv = get_nasdaq_ohlcv("AAPL", period="5d")
    if "error" in ohlcv:
        print("Error:", ohlcv["error"])
    else:
        print(f"Retrieved {len(ohlcv)} days of data.")
        first_date = next(iter(ohlcv))
        print(f"Sample data ({first_date}):", ohlcv[first_date])
