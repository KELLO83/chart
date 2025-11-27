"""Fetch and persist crypto OHLCV data via ccxt.

This helper keeps the CSV schema in ``stock_data`` aligned with what the
FastAPI app expects (date/open/high/low/close/volume).  It talks directly
to the configured ccxt exchange so we don't have to go through the stock
MCP server for crypto assets.

Example:
    python fetch_crypto_ohlcv.py --symbol BTC/USDT --days 730
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Iterable, List, Sequence

import ccxt  # type: ignore
import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
DATA_DIR = REPO_ROOT / "stock_data"


@dataclass
class FetchConfig:
    symbol: str = "BTC/USDT"
    timeframe: str = "1d"
    days: int = 730
    exchange_id: str = "binance"
    dataset_id: str | None = None
    output_path: Path | None = None

    def resolved_dataset_id(self) -> str:
        if self.dataset_id:
            return self.dataset_id
        normalized_symbol = self.symbol.replace("/", "")
        duration = f"{self.days // 365}Y" if self.days % 365 == 0 else f"{self.days}D"
        return f"{normalized_symbol}_{duration}_OHLCV"

    def resolved_output_path(self) -> Path:
        if self.output_path:
            return Path(self.output_path)
        DATA_DIR.mkdir(parents=True, exist_ok=True)
        return DATA_DIR / f"{self.resolved_dataset_id()}.csv"


def _instantiate_exchange(exchange_id: str) -> ccxt.Exchange:
    exchange_id = exchange_id.lower()
    if not hasattr(ccxt, exchange_id):
        raise ValueError(f"Unsupported exchange '{exchange_id}'")
    exchange_cls = getattr(ccxt, exchange_id)
    exchange: ccxt.Exchange = exchange_cls({"enableRateLimit": True})
    if not exchange.has.get("fetchOHLCV"):
        raise ValueError(f"Exchange '{exchange_id}' does not support fetchOHLCV")
    return exchange


def fetch_ohlcv_rows(cfg: FetchConfig) -> List[Sequence[float]]:
    exchange = _instantiate_exchange(cfg.exchange_id)
    since_ms = int(
        (datetime.now(timezone.utc) - timedelta(days=cfg.days)).timestamp() * 1000
    )
    timeframe_ms = int(exchange.parse_timeframe(cfg.timeframe) * 1000)
    rows: List[Sequence[float]] = []
    now_ms = exchange.milliseconds()

    while since_ms < now_ms:
        batch = exchange.fetch_ohlcv(
            cfg.symbol, cfg.timeframe, since_ms, limit=1000
        )
        if not batch:
            break
        rows.extend(batch)
        last_ts = batch[-1][0]
        next_since = last_ts + timeframe_ms
        if next_since <= since_ms:
            # should never happen, but guard against infinite loop
            break
        since_ms = next_since
        if last_ts >= now_ms:
            break
    return rows


def _format_dataframe(rows: Iterable[Sequence[float]]) -> pd.DataFrame:
    columns = ["timestamp", "open", "high", "low", "close", "volume"]
    frame = pd.DataFrame(rows, columns=columns)
    if frame.empty:
        return frame
    frame["date"] = (
        pd.to_datetime(frame["timestamp"], unit="ms", utc=True)
        .dt.tz_convert("UTC")
        .dt.tz_localize(None)
    )
    cleaned = (
        frame.drop(columns=["timestamp"])
        .dropna(subset=["open", "high", "low", "close"])
        .sort_values("date")
        .drop_duplicates(subset="date", keep="last")
    )
    numeric_cols = ["open", "high", "low", "close", "volume"]
    cleaned[numeric_cols] = cleaned[numeric_cols].apply(
        pd.to_numeric, errors="coerce"
    )
    return cleaned[["date", "open", "high", "low", "close", "volume"]]


def run(cfg: FetchConfig) -> Path:
    rows = fetch_ohlcv_rows(cfg)
    frame = _format_dataframe(rows)
    if frame.empty:
        raise RuntimeError("No OHLCV rows fetched; check the symbol/timeframe combination.")
    output_path = cfg.resolved_output_path()
    frame.to_csv(output_path, index=False)
    return output_path


def parse_args() -> FetchConfig:
    parser = argparse.ArgumentParser(description="Fetch crypto OHLCV data via ccxt.")
    parser.add_argument("--symbol", default="BTC/USDT", help="Trading pair symbol (default: BTC/USDT)")
    parser.add_argument("--timeframe", default="1d", help="ccxt timeframe (default: 1d)")
    parser.add_argument("--days", type=int, default=730, help="Number of days of history to fetch")
    parser.add_argument("--exchange", default="binance", help="ccxt exchange id (default: binance)")
    parser.add_argument("--dataset-id", help="Override dataset id used for the CSV filename")
    parser.add_argument("--output", type=Path, help="Explicit output path")
    args = parser.parse_args()
    return FetchConfig(
        symbol=args.symbol,
        timeframe=args.timeframe,
        days=args.days,
        exchange_id=args.exchange,
        dataset_id=args.dataset_id,
        output_path=args.output,
    )


def main() -> None:
    cfg = parse_args()
    output_path = run(cfg)
    print(f"Saved {cfg.symbol} {cfg.timeframe} data to {output_path}")


if __name__ == "__main__":
    main()
