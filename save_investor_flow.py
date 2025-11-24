#!/usr/bin/env python3
"""Utility to export investor trading volume by investor category.

This script relies on the existing MCP server implementation in
``kospi-kosdaq-stock-server`` so we don't duplicate API plumbing. It fetches a
slightly larger date window, then trims it down to the requested number of
business days (default: 7) so we get a predictable number of days even in the
presence of weekends/holidays.
"""

from __future__ import annotations

import argparse
import csv
import sys
from datetime import datetime, timedelta
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
from typing import List, Sequence

DEFAULT_DAYS = 7
FETCH_MARGIN_MULTIPLIER = 3  # grab extra calendar days to survive holidays/weekends

REPO_ROOT = Path(__file__).resolve().parent
SERVER_PATH = REPO_ROOT / "kospi-kosdaq-stock-server" / "kospi_kosdaq_stock_server.py"


def parse_date(value: str) -> str:
    """Normalize YYYYMMDD or YYYY-MM-DD into YYYYMMDD."""
    value = value.strip()
    for fmt in ("%Y%m%d", "%Y-%m-%d"):
        try:
            return datetime.strptime(value, fmt).strftime("%Y%m%d")
        except ValueError:
            continue
    raise argparse.ArgumentTypeError(
        f"날짜 형식이 잘못되었습니다. YYYYMMDD 또는 YYYY-MM-DD: {value}"
    )


def infer_fetch_range(to_date: str, days: int, from_date: str | None) -> tuple[str, str]:
    if from_date:
        return from_date, to_date
    target = datetime.strptime(to_date, "%Y%m%d")
    offset = timedelta(days=days * FETCH_MARGIN_MULTIPLIER)
    start = (target - offset).strftime("%Y%m%d")
    return start, to_date


def load_server_module():
    if not SERVER_PATH.exists():
        raise RuntimeError(f"서버 스크립트를 찾을 수 없습니다: {SERVER_PATH}")
    spec = spec_from_file_location("kospi_kosdaq_stock_server", SERVER_PATH)
    if spec is None or spec.loader is None:
        raise RuntimeError("서버 모듈 로드에 실패했습니다.")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[assignment]
    return module


def select_recent_dates(rows: Sequence[dict], days: int) -> List[dict]:
    if not rows:
        return []
    unique_dates = sorted({row["date"] for row in rows})
    keep = set(unique_dates[-days:])
    filtered = [row for row in rows if row["date"] in keep]
    filtered.sort(key=lambda r: (r["date"], r["investor"]))
    return filtered


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="투자주체별 수급 CSV 추출기")
    parser.add_argument("ticker", help="6자리 종목 코드 (예: 000660)")
    parser.add_argument(
        "--to-date",
        type=parse_date,
        default=datetime.now().strftime("%Y%m%d"),
        help="종료일 (기본: 오늘)",
    )
    parser.add_argument(
        "--from-date",
        type=parse_date,
        help="시작일. 지정하지 않으면 최근 일수 기준 자동 계산",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=DEFAULT_DAYS,
        help="가져올 영업일 수 (기본: 7일)",
    )
    parser.add_argument(
        "--output",
        type=str,
        help="저장할 CSV 경로 (기본: investor_flow_{ticker}_amount.csv)",
    )

    args = parser.parse_args(argv)
    if args.days <= 0:
        parser.error("--days 값은 1 이상의 정수여야 합니다.")

    from_date, to_date = infer_fetch_range(args.to_date, args.days, args.from_date)

    server = load_server_module()
    result = server.export_daily_investor_trading_volume(
        fromdate=from_date,
        todate=to_date,
        ticker=args.ticker,
    )
    if "error" in result:
        raise RuntimeError(result["error"])

    source_csv = Path(result["file"])
    if not source_csv.exists():
        raise RuntimeError(f"생성된 CSV를 찾을 수 없습니다: {source_csv}")

    with source_csv.open("r", encoding="utf-8-sig", newline="") as fh:
        reader = csv.DictReader(fh)
        rows = list(reader)

    trimmed_rows = select_recent_dates(rows, args.days)
    if not trimmed_rows:
        raise RuntimeError("필터링 후 남은 데이터가 없습니다.")

    output_path = (
        Path(args.output)
        if args.output
        else REPO_ROOT / f"investor_flow_{args.ticker}_amount.csv"
    )
    with output_path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=["date", "investor", "sell", "buy", "net"])
        writer.writeheader()
        writer.writerows(trimmed_rows)

    print(
        f"Saved {len(trimmed_rows)} rows (최근 {args.days} 영업일) to {output_path}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
