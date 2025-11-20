from __future__ import annotations

import pandas as pd

RSI_PERIOD = 14
RSI_COLOR = "#ffffff"

__all__ = ["compute_rsi", "RSI_PERIOD", "RSI_COLOR"]


def compute_rsi(close: pd.Series, period: int = RSI_PERIOD) -> pd.Series:
    """
    Compute the Relative Strength Index (RSI) for the provided closing prices.

    Args:
        close: Series of closing prices indexed by datetime.
        period: Look-back period for the RSI calculation (default: 14).

    Returns:
        Pandas Series representing the RSI values aligned with the input index.
    """
    if period <= 0:
        raise ValueError("period must be a positive integer.")

    if close.empty:
        return pd.Series(dtype="float64")

    # Price change from previous close
    delta = close.diff()
    gains = delta.clip(lower=0)
    losses = -delta.clip(upper=0)

    # Wilder's smoothing (EMA with alpha = 1/period)
    avg_gain = gains.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()
    avg_loss = losses.ewm(alpha=1 / period, adjust=False, min_periods=period).mean()

    rs = avg_gain / avg_loss.replace(0, float("nan"))
    rsi = 100 - (100 / (1 + rs))

    return rsi.fillna(0.0)
