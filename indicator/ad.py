import pandas as pd

def compute_ad(data: pd.DataFrame) -> pd.Series:
    """
    Compute Accumulation/Distribution (A/D) Line.
    
    Formula:
        CLV = ((Close - Low) - (High - Close)) / (High - Low)
        * If High == Low, CLV = 0
        A/D = Cumulative Sum of (CLV * Volume)
    """
    if data.empty:
        return pd.Series(dtype=float)

    high = data["high"]
    low = data["low"]
    close = data["close"]
    volume = data["volume"]

    # Calculate CLV (Close Location Value)
    # Handle division by zero where High == Low
    range_hl = high - low
    clv = ((close - low) - (high - close)) / range_hl
    clv = clv.fillna(0.0)  # Replace NaN (0/0) with 0
    
    # Calculate A/D
    ad = (clv * volume).cumsum()
    
    return ad
