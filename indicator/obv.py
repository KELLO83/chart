from __future__ import annotations

import pandas as pd

__all__ = ["compute_obv"]


def compute_obv(close: pd.Series, volume: pd.Series) -> pd.Series:
    """Compute the On-Balance Volume (OBV) indicator.

    Args:
        close: Series of closing prices indexed by datetime.
        volume: Series of traded volume indexed by datetime.

    Returns:
        Pandas Series containing the OBV values aligned with the
        overlapping index of ``close`` and ``volume``.
    """

    if close.empty or volume.empty:
        return pd.Series(dtype="float64")

    data = pd.concat({"close": close, "volume": volume}, axis=1).dropna()
    if data.empty:
        return pd.Series(dtype="float64")

    # TradingView-style OBV starts at 0 and accumulates thereafter.
    obv = pd.Series(index=data.index, dtype="float64")
    obv.iloc[0] = 0.0

    for idx in range(1, len(data)):
        prev_obv = obv.iloc[idx - 1]
        curr_close = data["close"].iloc[idx]
        prev_close = data["close"].iloc[idx - 1]
        curr_volume = float(data["volume"].iloc[idx])

        if curr_close > prev_close:
            obv.iloc[idx] = prev_obv + curr_volume
        elif curr_close < prev_close:
            obv.iloc[idx] = prev_obv - curr_volume
        else:
            obv.iloc[idx] = prev_obv

    return obv
