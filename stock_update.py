"""Utility helpers for keeping `stock_data` CSV files up to date.

이 모듈은 kospi-kosdaq MCP 서버(내부 pykrx wrapper)를 직접 호출해
부족한 거래일 구간만 가져와 CSV를 갱신하는 로직만 정의한다.
실제 버튼이나 UI 이벤트에 연결하지 않고 별도의 스크립트/스케줄러에서
이 클래스를 import 해 사용하면 된다.
"""

from __future__ import annotations

import json
import logging
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable, Dict, Iterable, Optional

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parent
STOCK_DATA_DIR = REPO_ROOT / "stock_data"
DATASET_TICKER_FILE = STOCK_DATA_DIR / "dataset_tickers.json"

# Allow importing the MCP server module directly so we can reuse its tool functions.
SERVER_MODULE_DIR = REPO_ROOT / "kospi-kosdaq-stock-server"
if SERVER_MODULE_DIR.exists():
    sys.path.append(str(SERVER_MODULE_DIR))

try:
    # pylint: disable=wrong-import-position
    from kospi_kosdaq_stock_server import get_stock_ohlcv  # type: ignore
except Exception:  # pragma: no cover - module may not be installed during linting
    get_stock_ohlcv = None  # type: ignore


# Mapping between various column names returned by pykrx and the CSV schema.
COLUMN_ALIASES: Dict[str, Iterable[str]] = {
    "open": ("open", "Open", "시가"),
    "high": ("high", "High", "고가"),
    "low": ("low", "Low", "저가"),
    "close": ("close", "Close", "종가"),
    "volume": ("volume", "Volume", "거래량"),
}


def _default_fetcher(*, start: str, end: str, ticker: str, adjusted: bool = True) -> Dict[str, Any]:
    if get_stock_ohlcv is None:
        raise RuntimeError("kospi_kosdaq_stock_server 모듈을 찾을 수 없습니다.")
    return get_stock_ohlcv(start, end, ticker, adjusted=adjusted)


@dataclass
class StockDataUpdater:
    """Encapsulates the CSV update workflow.

    Args:
        data_dir: CSV 파일이 저장된 디렉터리.
        dataset_tickers: dataset_id -> ticker 매핑.
        fetcher: 원격 데이터 호출 함수. 기본은 MCP 서버의 get_stock_ohlcv.
        fetcher_kwargs: fetcher에 항상 전달할 기본 kwargs.
        market_open_time: 저장할 timestamp에 붙일 시각(기본 09:00).
        fallback_days: CSV가 비었을 때 가져올 기본 일수.
    """

    data_dir: Path = STOCK_DATA_DIR
    dataset_tickers: Optional[Dict[str, str]] = None
    fetcher: Optional[Callable[..., Dict[str, Any]]] = None
    fetcher_kwargs: Dict[str, Any] = field(default_factory=lambda: {"adjusted": True})
    market_open_time: time = time(9, 0)
    fallback_days: int = 730

    def __post_init__(self) -> None:
        self.data_dir = Path(self.data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)
        if self.dataset_tickers is None:
            self.dataset_tickers = self._load_dataset_tickers()
        if self.fetcher is None:
            self.fetcher = _default_fetcher

    # ---- public API ----------------------------------------------------- #

    def update_all(self) -> None:
        """Iterate through mapped datasets and update missing windows."""
        for dataset_id in sorted(self.dataset_tickers):
            try:
                updated = self.update_dataset(dataset_id)
                if updated is None:
                    logging.info("[%s] Already up to date", dataset_id)
                else:
                    logging.info("[%s] Appended %d new rows", dataset_id, len(updated))
            except Exception as exc:  # pragma: no cover - operational logging
                logging.error("[%s] Update failed: %s", dataset_id, exc)

    def update_dataset(self, dataset_id: str) -> Optional[pd.DataFrame]:
        """Update a single dataset. Returns the rows that were appended."""
        ticker = self.dataset_tickers.get(dataset_id)
        if not ticker:
            logging.warning("Unknown dataset_id '%s'; skipping", dataset_id)
            return None

        csv_path = self.data_dir / f"{dataset_id}.csv"
        if not csv_path.exists():
            logging.warning("CSV %s not found; skipping", csv_path)
            return None

        local_df = self._read_csv(csv_path)
        window = self._compute_fetch_window(local_df)
        if window is None:
            return None

        start_dt, end_dt = window
        remote_frame = self._fetch_remote_frame(
            ticker=ticker,
            start=start_dt.strftime("%Y%m%d"),
            end=end_dt.strftime("%Y%m%d"),
        )
        if remote_frame.empty:
            logging.info("[%s] No new remote rows", dataset_id)
            return None

        filtered_remote = remote_frame[
            (remote_frame["date"] >= pd.Timestamp(start_dt))
            & (remote_frame["date"] <= pd.Timestamp(end_dt))
        ]
        if filtered_remote.empty:
            logging.info("[%s] Remote rows already exist locally", dataset_id)
            return None

        updated_df = (
            pd.concat([local_df, filtered_remote], ignore_index=True)
            .drop_duplicates(subset="date")
            .sort_values("date")
        )
        self._write_csv(csv_path, updated_df)
        return filtered_remote

    # ---- helpers -------------------------------------------------------- #

    def _read_csv(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(path, parse_dates=["date"])
        return frame.sort_values("date").reset_index(drop=True)

    def _write_csv(self, path: Path, frame: pd.DataFrame) -> None:
        frame.to_csv(path, index=False)

    def _load_dataset_tickers(self) -> Dict[str, str]:
        mapping_path = DATASET_TICKER_FILE
        if not mapping_path.exists():
            raise FileNotFoundError(
                f"dataset_tickers.json을 찾을 수 없습니다. {mapping_path} 위치에 파일을 생성하세요."
            )
        try:
            data = json.loads(mapping_path.read_text(encoding="utf-8"))
            return {k: str(v) for k, v in data.items()}
        except Exception as exc:
            raise RuntimeError(f"{mapping_path} 파싱 실패: {exc}") from exc

    def _compute_fetch_window(self, local_df: pd.DataFrame) -> Optional[tuple[date, date]]:
        today = datetime.now().date()
        if not len(local_df):
            start = today - timedelta(days=self.fallback_days)
        else:
            last_date = local_df["date"].max().date()
            start = last_date + timedelta(days=1)
        if start > today:
            return None
        return start, today

    def _fetch_remote_frame(self, *, ticker: str, start: str, end: str) -> pd.DataFrame:
        assert self.fetcher is not None, "fetcher must be configured"
        payload = self.fetcher(start=start, end=end, ticker=ticker, **self.fetcher_kwargs)
        if not isinstance(payload, dict):
            raise RuntimeError(f"Unexpected payload type: {type(payload)}")
        if "error" in payload:
            raise RuntimeError(payload["error"])
        frame = pd.DataFrame.from_dict(payload, orient="index")
        if frame.empty:
            return frame

        frame.index = pd.to_datetime(frame.index)
        frame = self._rename_columns(frame)
        numeric_cols = ["open", "high", "low", "close", "volume"]
        frame[numeric_cols] = frame[numeric_cols].apply(pd.to_numeric, errors="coerce")
        frame = frame.dropna(subset=["open", "high", "low", "close"])
        frame = (
            frame.rename_axis("date")
            .reset_index()
            .assign(date=lambda df: self._apply_market_time(df["date"]))
        )
        frame = frame.sort_values("date").reset_index(drop=True)
        return frame[["date", "open", "high", "low", "close", "volume"]]

    def _rename_columns(self, frame: pd.DataFrame) -> pd.DataFrame:
        rename_map: Dict[str, str] = {}
        for canonical, aliases in COLUMN_ALIASES.items():
            for alias in aliases:
                if alias in frame.columns:
                    rename_map[alias] = canonical
                    break
            if canonical not in rename_map.values():
                frame[canonical] = pd.NA
        return frame.rename(columns=rename_map)

    def _apply_market_time(self, series: pd.Series) -> pd.Series:
        base = series.dt.normalize()
        delta = timedelta(
            hours=self.market_open_time.hour,
            minutes=self.market_open_time.minute,
            seconds=self.market_open_time.second,
        )
        return base + delta


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    updater = StockDataUpdater()
    updater.update_all()
