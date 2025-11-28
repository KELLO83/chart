"""Utility script to compute CVD candles from 5-minute intraday data."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import pandas as pd
import yfinance as yf


DEFAULT_PERIOD = "59d"  # yfinance limit for 5m data (~60d)
DEFAULT_INTERVAL = "5m"
EXPORT_PATH = Path(__file__).with_name("nasdaq_data") / "AAPL_CVD.csv"


@dataclass
class Candle:
    date: pd.Timestamp
    open: float
    high: float
    low: float
    close: float


def fetch_intraday_data(ticker: str) -> pd.DataFrame:
    """Download 5-minute OHLCV data for the requested ticker."""
    df = yf.download(ticker, period=DEFAULT_PERIOD, interval=DEFAULT_INTERVAL, progress=False)
    if df.empty:
        raise ValueError(f"{ticker} 5분 데이터를 가져오지 못했습니다.")
    if isinstance(df.columns, pd.MultiIndex):
        df.columns = df.columns.get_level_values(0)
    df = df.rename(columns={
        "Open": "open",
        "High": "high",
        "Low": "low",
        "Close": "close",
        "Volume": "volume",
    })
    return df[["open", "high", "low", "close", "volume"]]


def compute_daily_cvd(df: pd.DataFrame) -> pd.DataFrame:
    """Transform 5m bars into daily CVD candles."""
    if df.empty:
        raise ValueError("입력된 데이터가 비어 있습니다.")
    delta = df.apply(_calc_delta_per_row, axis=1)
    df = df.copy()
    df["delta"] = delta
    df["date"] = df.index.date

    records = []
    for date_value, group in df.groupby("date"):
        cumsum = group["delta"].cumsum()
        high = max(0, cumsum.max())
        low = min(0, cumsum.min())
        close = cumsum.iloc[-1]
        records.append(
            {
                "date": pd.Timestamp(date_value),
                "open": 0.0,
                "high": float(high),
                "low": float(low),
                "close": float(close),
            }
        )

    return pd.DataFrame(records)


def _calc_delta_per_row(row: pd.Series) -> float:
    if row["close"] > row["open"]:
        return float(row["volume"])
    if row["close"] < row["open"]:
        return -float(row["volume"])
    return 0.0


def export_cvd_csv(ticker: str, output_path: Optional[Path] = None) -> Path:
    five_min = fetch_intraday_data(ticker)
    cvd_df = compute_daily_cvd(five_min)
    if output_path is None:
        output_path = EXPORT_PATH
    output_path.parent.mkdir(parents=True, exist_ok=True)
    cvd_df.to_csv(output_path, index=False)
    print(f"{ticker} CVD {len(cvd_df)}행 저장 완료: {output_path}")
    return output_path


if __name__ == "__main__":
    try:
        export_cvd_csv("AAPL")
    except Exception as exc:
        print(f"에러: {exc}")


"""
import pandas as pd
from pathlib import Path
from typing import List, Dict, Any, Optional

CVD_DIR = Path(__file__).parent / "nasdaq_data" / "cvd"

def get_daily_cvd_candles(ticker: str) -> List[Dict[str, Any]]:
    """
    Reads Daily CVD candles from a pre-calculated CSV file.
    Path: nasdaq_data/cvd/{ticker}_CVD.csv
    
    Expected CSV columns: date, open, high, low, close
    """
    csv_path = CVD_DIR / f"{ticker}_CVD.csv"
    
    if not csv_path.exists():
        # print(f"CVD file not found for {ticker}: {csv_path}")
        return []

    try:
        df = pd.read_csv(csv_path)
        
        # Ensure columns exist
        required = {"date", "open", "high", "low", "close"}
        if not required.issubset(df.columns):
            print(f"Invalid columns in {csv_path}: {df.columns}")
            return []
            
        # Parse date
        df["date"] = pd.to_datetime(df["date"])
        
        cvd_candles = []
        for _, row in df.iterrows():
            date_val = row["date"]
            candle = {
                "time": {
                    "year": date_val.year,
                    "month": date_val.month,
                    "day": date_val.day,
                },
                "open": float(row["open"]),
                "high": float(row["high"]),
                "low": float(row["low"]),
                "close": float(row["close"])
            }
            cvd_candles.append(candle)
            
        return cvd_candles

    except Exception as e:
        print(f"Error reading CVD CSV for {ticker}: {e}")
        return []

if __name__ == "__main__":
    # Test
    res = get_daily_cvd_candles("AAPL")
    print(f"Loaded {len(res)} CVD candles for AAPL")
    if res:
        print(res[-1])
