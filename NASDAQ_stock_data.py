import yfinance as yf
import pandas as pd
from datetime import datetime, timedelta
from pathlib import Path
from typing import Optional, Dict, Any

def get_us_stock_ohlcv(
    ticker: str,
    start_date: Optional[str] = None,
    end_date: Optional[str] = None,
    period: str = "1mo",
    interval: str = "1d"
) -> pd.DataFrame:
    """
    Fetch OHLCV data for a US stock using yfinance.

    Args:
        ticker (str): The stock ticker symbol (e.g., 'AAPL', 'TSLA', 'NVDA').
        start_date (str, optional): Start date in 'YYYY-MM-DD' format.
        end_date (str, optional): End date in 'YYYY-MM-DD' format.
        period (str, optional): Data period to download if start/end not provided 
                                (e.g., '1d', '5d', '1mo', '3mo', '6mo', '1y', '2y', '5y', '10y', 'ytd', 'max').
        interval (str, optional): Data interval (e.g., '1m', '2m', '5m', '15m', '30m', '60m', '90m', '1h', '1d', '5d', '1wk', '1mo', '3mo').

    Returns:
        pd.DataFrame: DataFrame containing OHLCV data.
    """
    print(f"Fetching data for {ticker}...")
    
    try:
        # If start_date and end_date are provided, use them
        if start_date and end_date:
            data = yf.download(ticker, start=start_date, end=end_date, interval=interval, progress=False)
        else:
            # Otherwise use period
            data = yf.download(ticker, period=period, interval=interval, progress=False)

        if data.empty:
            print(f"No data found for {ticker}.")
            return pd.DataFrame()

        # yfinance returns a MultiIndex columns if multiple tickers, but here we ask for one.
        # However, sometimes it returns columns like ('Close', 'AAPL').
        # We flatten/clean the columns just in case.
        if isinstance(data.columns, pd.MultiIndex):
            data.columns = data.columns.get_level_values(0)

        # Ensure standard columns
        data = data.rename(columns={
            "Open": "open",
            "High": "high",
            "Low": "low",
            "Close": "close",
            "Volume": "volume"
        })
        
        # Keep only OHLCV
        required_cols = ["open", "high", "low", "close", "volume"]
        available_cols = [c for c in required_cols if c in data.columns]
        data = data[available_cols]
        
        # Reset index to make Date a column if needed, or keep it as index.
        # For now, let's keep it as index but ensure it's datetime.
        data.index = pd.to_datetime(data.index)
        
        return data

    except Exception as e:
        print(f"Error fetching data for {ticker}: {e}")
        return pd.DataFrame()

if __name__ == "__main__":
    target_ticker = "AAPL"  # Apple
    output_dir = Path(__file__).parent / "nasdaq_data"
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / f"{target_ticker}_2Y_OHLCV.csv"

    print(f"--- Downloading 2Y OHLCV for {target_ticker} ---")
    two_year_df = get_us_stock_ohlcv(target_ticker, period="2y")

    if two_year_df.empty:
        print("Failed to download Apple data. CSV was not created.")
    else:
        export_df = two_year_df.copy()
        export_df.index.name = "date"
        export_df = export_df.reset_index()
        export_df.to_csv(output_path, index=False)
        print(f"Saved {len(export_df)} rows to {output_path}")
