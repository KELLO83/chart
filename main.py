from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional, Union

import pandas as pd
from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse
import uvicorn

from indicator.rsi import RSI_COLOR, compute_rsi
from indicator.obv import compute_obv


DATA_DIR = Path(__file__).with_name("stock_data")
DEFAULT_DATASET_ID = "ETHUSDT_2Y_OHLCV_Trans"
UP_COLOR = "#089981"
DOWN_COLOR = "#f23645"
UP_VOLUME_COLOR = "rgba(8, 153, 129, 0.4)"
DOWN_VOLUME_COLOR = "rgba(242, 54, 69, 0.4)"
OBV_COLOR = "#008080"  # teal tone for OBV line
ALLOWED_INTERVAL_RULES = {
    "1d": "1D",
    "3d": "3D",
    "1w": "1W",
}


def load_price_data(csv_path: Path) -> pd.DataFrame:
    """Load and clean OHLCV data from CSV."""
    data = (
        pd.read_csv(csv_path, parse_dates=["date"])
        .set_index("date")
        .sort_index()
    )
    numeric_cols = ["open", "high", "low", "close", "volume"]
    data[numeric_cols] = data[numeric_cols].apply(
        pd.to_numeric, errors="coerce"
    )
    return data.dropna(subset=numeric_cols)


def get_dataset_catalog() -> Dict[str, Path]:
    if not DATA_DIR.exists():
        raise ValueError("stock_data 폴더를 찾을 수 없습니다.")
    csv_files = sorted(p for p in DATA_DIR.iterdir() if p.suffix.lower() == ".csv")
    if not csv_files:
        raise ValueError("stock_data 폴더에 CSV 데이터셋이 없습니다.")
    return {csv.stem: csv for csv in csv_files}


def get_default_dataset_id() -> str:
    catalog = get_dataset_catalog()
    if DEFAULT_DATASET_ID in catalog:
        return DEFAULT_DATASET_ID
    return next(iter(catalog.keys()))


def normalize_dataset_id(dataset_id: Optional[str]) -> str:
    catalog = get_dataset_catalog()
    target = dataset_id.strip() if dataset_id else ""
    if not target:
        return get_default_dataset_id()
    if target not in catalog:
        raise ValueError(
            f"지원하지 않는 데이터셋입니다. 사용 가능: {', '.join(sorted(catalog))}"
        )
    return target


def _normalize_time_payload(
    date_value: pd.Timestamp, is_crypto: bool = False
) -> Union[int, Dict[str, int]]:
    """Normalize timestamps for chart payloads.

    Crypto는 24/7 데이터라 연속 unix 초를 그대로 사용하지만,
    주식(영업일만 포함)의 경우 거래일 기준 좌표를 줘야 확대 시 캔들이 밀리지 않는다.
    """
    if is_crypto:
        return int(date_value.timestamp())
    date_only = date_value.to_pydatetime()
    return {
        "year": date_only.year,
        "month": date_only.month,
        "day": date_only.day,
    }


def is_crypto_dataset(dataset_id: str) -> bool:
    """Determine if the dataset is a crypto pair based on its ID."""
    keywords = {"ETH", "BTC", "USDT", "BNB", "XRP", "SOL", "ADA", "DOGE"}
    upper_id = dataset_id.upper()
    return any(k in upper_id for k in keywords)


@lru_cache(maxsize=None)
def get_price_data(dataset_id: str) -> pd.DataFrame:
    catalog = get_dataset_catalog()
    csv_path = catalog.get(dataset_id)
    if not csv_path:
        raise ValueError("선택한 데이터셋을 찾을 수 없습니다.")
    data = load_price_data(csv_path)
    if data.empty:
        raise ValueError("유효한 차트 데이터가 없습니다.")
    return data


def normalize_interval(interval: str) -> str:
    default_interval = "1d"
    if not interval:
        return default_interval
    normalized = interval.lower()
    if normalized not in ALLOWED_INTERVAL_RULES:
        raise ValueError("지원하지 않는 인터벌입니다. (가능: 1d, 3d, 1w)")
    return normalized


def resample_price_data(data: pd.DataFrame, interval: str) -> pd.DataFrame:
    if interval == "1d":
        return data
    rule = ALLOWED_INTERVAL_RULES[interval]
    aggregated = (
        data.resample(rule, label="right", closed="right")
        .agg(
            {
                "open": "first",
                "high": "max",
                "low": "min",
                "close": "last",
                "volume": "sum",
            }
        )
        .dropna(subset=["open", "high", "low", "close"])
    )
    aggregated["volume"] = aggregated["volume"].fillna(0.0)
    if aggregated.empty:
        raise ValueError("선택한 인터벌에 대한 데이터가 부족합니다.")
    return aggregated


@lru_cache(maxsize=None)
def _build_payload(dataset_id: str, normalized_interval: str) -> Dict[str, Any]:
    base_data = get_price_data(dataset_id)
    working = resample_price_data(base_data, normalized_interval)
    is_crypto = is_crypto_dataset(dataset_id)
    return format_chart_payload(working, is_crypto)


def get_dataset_summary(dataset_id: str) -> Dict[str, Any]:
    data = get_price_data(dataset_id)
    start = data.index.min()
    end = data.index.max()
    return {
        "id": dataset_id,
        "label": dataset_id.replace("_", " "),
        "rows": len(data),
        "range": f"{start.strftime('%Y-%m-%d')} ~ {end.strftime('%Y-%m-%d')}",
    }


def format_chart_payload(data: pd.DataFrame, is_crypto: bool = False) -> Dict[str, Any]:
    candles: List[Dict] = []
    volumes: List[Dict] = []
    rsi_points: List[Dict] = []
    obv_points: List[Dict] = []
    rsi_series = compute_rsi(data["close"])
    obv_series = (
        compute_obv(data["close"], data["volume"])
        .reindex(data.index, method="ffill")
        .fillna(0.0)
    )

    for timestamp, row in data.iterrows():
        time_payload = _normalize_time_payload(timestamp, is_crypto)
        candle = {
            "time": time_payload,
            "open": float(row["open"]),
            "high": float(row["high"]),
            "low": float(row["low"]),
            "close": float(row["close"]),
        }
        candles.append(candle)
        volumes.append(
            {
                "time": time_payload,
                "value": float(row["volume"]),
                "color": UP_VOLUME_COLOR
                if row["close"] >= row["open"]
                else DOWN_VOLUME_COLOR,
            }
        )
        rsi_points.append(
            {"time": time_payload, "value": float(rsi_series.loc[timestamp])}
        )
        obv_points.append(
            {"time": time_payload, "value": float(obv_series.loc[timestamp])}
        )

    return {
        "type": "crypto" if is_crypto else "stock",
        "candles": candles,
        "volumes": volumes,
        "rsi": rsi_points,
        "obv": obv_points,
    }


app = FastAPI(title="ETH/USDT Candlestick Chart")


@app.get("/api/candles")
def read_candles(
    interval: str = "1d",
    dataset: Optional[str] = None,
) -> Dict[str, Any]:
    try:
        normalized_interval = normalize_interval(interval)
        dataset_id = normalize_dataset_id(dataset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        payload = _build_payload(dataset_id, normalized_interval)
        return payload
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/datasets")
def list_datasets() -> List[Dict[str, Any]]:
    try:
        catalog = get_dataset_catalog()
    except ValueError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    default_id = get_default_dataset_id()
    payload: List[Dict[str, Any]] = []
    for dataset_id in sorted(catalog.keys()):
        summary = get_dataset_summary(dataset_id)
        summary["default"] = dataset_id == default_id
        payload.append(summary)
    return payload


@app.get("/", response_class=HTMLResponse)
def index() -> str:
    """Serve a lightweight single-page chart UI."""
    template = """
<!DOCTYPE html>
<html lang="ko">
<head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>ETH/USDT · 캔들 차트</title>
    <link rel="preconnect" href="https://unpkg.com" />
    <style>
        :root {
            color-scheme: dark;
        }
        html, body {
            height: 100%;
        }
        body {
            margin: 0;
            font-family: "Pretendard", "Inter", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #000000;
            color: #c7cfde;
            display: flex;
            flex-direction: column;
            min-height: 100vh;
            overflow: hidden;
        }
        body.modal-open {
            overflow: hidden;
        }
        header {
            padding: 0.95rem 1.75rem;
            border-bottom: 1px solid #1c2032;
            background: linear-gradient(180deg, #050505, #000000);
            box-shadow: 0 10px 30px rgba(0, 0, 0, 0.6);
            display: flex;
            align-items: center;
            justify-content: space-between;
            flex-wrap: wrap;
            gap: 0.85rem;
        }
        .header-title {
            display: flex;
            flex-direction: column;
            gap: 0.15rem;
        }
        .header-title h1 {
            font-size: 1rem;
            font-weight: 500;
            letter-spacing: 0.04em;
            color: #e3e9ff;
            margin: 0;
        }
        .header-title p {
            margin: 0;
            font-size: 0.8rem;
            color: #7f8db4;
        }
        .header-controls {
            display: flex;
            align-items: center;
            gap: 1rem;
            flex-wrap: wrap;
        }
        .dataset-picker {
            display: flex;
            flex-direction: column;
            gap: 0.25rem;
            min-width: 230px;
        }
        .dataset-picker label {
            font-size: 0.7rem;
            color: #7f8db4;
            text-transform: uppercase;
            letter-spacing: 0.08em;
        }
        select#dataset-select {
            appearance: none;
            padding: 0.45rem 0.85rem;
            border-radius: 999px;
            border: 1px solid rgba(38, 52, 84, 0.8);
            background: #0b1223;
            color: #dbe5ff;
            font-weight: 500;
            min-width: 220px;
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.3);
        }
        select#dataset-select:focus {
            outline: none;
            border-color: #2d8cff;
            box-shadow: 0 0 0 2px rgba(45, 140, 255, 0.2);
        }
        .pill-button {
            border: none;
            background: linear-gradient(135deg, #162136, #10182b);
            color: #8f9bb8;
            font-size: 0.85rem;
            font-weight: 500;
            padding: 0.35rem 1rem;
            border-radius: 999px;
            cursor: pointer;
            transition: color 0.2s ease, background 0.2s ease, box-shadow 0.2s ease;
        }
        .pill-button.active {
            color: #ffffff;
            box-shadow: inset 0 0 12px rgba(25, 168, 255, 0.35);
            background: linear-gradient(135deg, #1f2d4a, #1a2440);
        }
        .interval-toggle {
            display: inline-flex;
            background: #0b1223;
            border-radius: 999px;
            border: 1px solid rgba(47, 63, 101, 0.7);
            padding: 0.15rem;
            gap: 0.15rem;
            box-shadow: inset 0 0 15px rgba(0, 0, 0, 0.35);
        }
        .interval-button {
            border: none;
            background: transparent;
            color: #8f9bb8;
            font-size: 0.85rem;
            font-weight: 500;
            padding: 0.35rem 0.9rem;
            border-radius: 999px;
            cursor: pointer;
            transition: color 0.2s ease, background 0.2s ease;
        }
        .interval-button:hover {
            color: #d6defa;
        }
        .interval-button.active {
            background: linear-gradient(135deg, #1f2d4a, #1a2440);
            color: #ffffff;
            box-shadow: inset 0 0 12px rgba(25, 168, 255, 0.35);
        }
        .interval-button:disabled {
            opacity: 0.6;
            cursor: default;
        }
        main {
            flex: 1;
            padding: 0 1.5rem 1.5rem;
            min-height: 0;
        }
        .chart-stack {
            display: flex;
            flex-direction: column;
            gap: 0.45rem;
            height: 100%;
            min-height: 0;
        }
        .chart-panel {
            flex: 1 1 0%;
            min-height: 120px;
            background: #000000;
            border: 1px solid #161a28;
            border-radius: 10px;
            box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.6);
            position: relative;
            overflow: hidden;
        }
        .chart-panel.price {
            flex-grow: 4.8;
        }
        .chart-panel.obv {
            flex-grow: 1.8;
        }
        .chart-panel.rsi {
            flex-grow: 1.8;
            padding-bottom: 0.35rem;
        }
        .cursor-date-label {
            position: absolute;
            bottom: 6px;
            left: 50%;
            transform: translateX(-50%);
            padding: 0.2rem 0.65rem;
            border-radius: 6px;
            border: 1px solid rgba(34, 44, 70, 0.9);
            background: rgba(9, 13, 26, 0.92);
            color: #e6edff;
            font-size: 0.75rem;
            font-weight: 600;
            letter-spacing: 0.05em;
            box-shadow: 0 6px 12px rgba(0, 0, 0, 0.55);
            pointer-events: none;
            opacity: 0;
            transition: opacity 0.15s ease;
            z-index: 10;
        }
        .cursor-date-label[aria-hidden="false"] {
            opacity: 1;
        }
        .panel-resizer {
            height: 14px;
            border-radius: 999px;
            border: 1px solid rgba(22, 26, 40, 0.95);
            background: radial-gradient(circle, rgba(25, 35, 64, 0.7), rgba(8, 10, 22, 0.95));
            box-shadow: inset 0 0 10px rgba(0, 0, 0, 0.7);
            cursor: row-resize;
            display: flex;
            align-items: center;
            justify-content: center;
            user-select: none;
            touch-action: none;
        }
        .panel-resizer::before {
            content: "";
            width: 80px;
            height: 3px;
            border-radius: 999px;
            background: linear-gradient(90deg, rgba(73, 129, 255, 0.3), rgba(66, 220, 255, 0.6), rgba(73, 129, 255, 0.3));
            box-shadow: 0 0 8px rgba(66, 220, 255, 0.35);
        }
        .panel-resizer.dragging {
            background: linear-gradient(120deg, rgba(20, 28, 52, 0.95), rgba(10, 14, 28, 0.95));
        }
        body.panel-resize-active {
            user-select: none;
            cursor: row-resize;
        }
        .chart-surface {
            width: 100%;
            height: 100%;
        }
        .chart-toolbar {
            position: absolute;
            top: 0.4rem;
            left: 0.55rem;
            display: flex;
            gap: 0.4rem;
            z-index: 5;
        }
        .status-bar {
            display: flex;
            align-items: center;
            justify-content: space-between;
            padding: 0.65rem 1.75rem;
            border-bottom: 1px solid #0a0c12;
            background: linear-gradient(120deg, rgba(5, 8, 18, 0.98), rgba(3, 5, 12, 0.98));
            font-family: "JetBrains Mono", "Roboto Mono", monospace;
            font-size: 0.78rem;
            color: #9ea8c7;
            gap: 1rem;
            flex-wrap: wrap;
            box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.45);
        }
        .status-left {
            display: flex;
            gap: 0.45rem;
            align-items: baseline;
        }
        .status-symbol {
            font-weight: 600;
            color: #f5f6ff;
            font-size: 0.95rem;
            letter-spacing: 0.04em;
        }
        .status-range {
            color: #6a769a;
            font-size: 0.72rem;
            letter-spacing: 0.02em;
        }
        .status-values {
            display: flex;
            gap: 0.45rem;
            flex-wrap: wrap;
        }
        .status-value {
            display: inline-flex;
            align-items: center;
            gap: 0.35rem;
            padding: 0.15rem 0.75rem;
            border-radius: 6px;
            border: 1px solid rgba(23, 28, 46, 0.95);
            background: linear-gradient(145deg, rgba(10, 14, 27, 0.95), rgba(7, 9, 19, 0.9));
            box-shadow: 0 6px 16px rgba(0, 0, 0, 0.45);
            white-space: nowrap;
            color: #dfe4ff;
            min-height: 30px;
        }
        .status-value strong {
            color: #8b98b9;
            font-weight: 600;
            font-size: 0.72rem;
            letter-spacing: 0.08em;
        }
        .status-value .status-data {
            color: #f5f7ff;
            font-weight: 500;
            font-size: 0.82rem;
        }
        .status-value.date {
            min-width: 180px;
        }
    </style>
    <script src="https://unpkg.com/lightweight-charts@4.1.1/dist/lightweight-charts.standalone.production.js"></script>
</head>
<body>
    <header>
        <div class="header-title">
            <h1>멀티 데이터셋 · 캔들 차트</h1>
            <p id="dataset-meta">데이터셋 정보를 불러오는 중...</p>
        </div>
        <div class="header-controls">
            <div class="dataset-picker">
                <label for="dataset-select">DATASET</label>
                <select id="dataset-select" aria-label="데이터셋 선택"></select>
            </div>
            <div class="interval-toggle" role="group" aria-label="차트 주기 선택">
                <button type="button" class="interval-button active" data-interval="1d">1일</button>
                <button type="button" class="interval-button" data-interval="3d">3일</button>
                <button type="button" class="interval-button" data-interval="1w">1주</button>
            </div>
        </div>
    </header>
    <div class="status-bar">
        <div class="status-left">
            <span id="status-symbol" class="status-symbol">--</span>
            <span id="status-range" class="status-range">--</span>
        </div>
        <div class="status-values">
            <span class="status-value date"><strong>DATE</strong><span id="status-date" class="status-data">--</span></span>
            <span class="status-value"><strong>O</strong><span id="status-open" class="status-data">--</span></span>
            <span class="status-value"><strong>H</strong><span id="status-high" class="status-data">--</span></span>
            <span class="status-value"><strong>L</strong><span id="status-low" class="status-data">--</span></span>
            <span class="status-value"><strong>C</strong><span id="status-close" class="status-data">--</span></span>
            <span class="status-value"><strong>V</strong><span id="status-volume" class="status-data">--</span></span>
            <span class="status-value"><strong>RSI</strong><span id="status-rsi" class="status-data">--</span></span>
            <span class="status-value"><strong>OBV</strong><span id="status-obv" class="status-data">--</span></span>
        </div>
    </div>
    <main>
        <div class="chart-stack">
            <div class="chart-panel price" data-panel-id="price" data-min-height="180">
                <div class="chart-toolbar">
                    <button type="button" id="volume-toggle" class="pill-button active">거래량 표시</button>
                </div>
                <div id="price-chart" class="chart-surface"></div>
                <div id="cursor-date-label" class="cursor-date-label" aria-hidden="true"></div>
            </div>
            <div class="panel-resizer" role="separator" aria-label="OBV 패널 크기 조절" aria-orientation="horizontal"></div>
            <div class="chart-panel obv" data-panel-id="obv" data-min-height="120">
                <div id="obv-chart" class="chart-surface"></div>
            </div>
            <div class="panel-resizer" role="separator" aria-label="RSI 패널 크기 조절" aria-orientation="horizontal"></div>
            <div class="chart-panel rsi" data-panel-id="rsi" data-min-height="120">
                <div id="rsi-chart" class="chart-surface"></div>
            </div>
        </div>
    </main>
    <script>
        const priceContainer = document.getElementById("price-chart");
        const rsiContainer = document.getElementById("rsi-chart");
        const obvContainer = document.getElementById("obv-chart");
        const datasetSelect = document.getElementById("dataset-select");
        const datasetMeta = document.getElementById("dataset-meta");
        const intervalButtons = document.querySelectorAll(
            ".interval-toggle .interval-button"
        );
        const volumeToggle = document.getElementById("volume-toggle");
        const statusSymbol = document.getElementById("status-symbol");
        const statusRange = document.getElementById("status-range");
        const statusDate = document.getElementById("status-date");
        const statusOpen = document.getElementById("status-open");
        const statusHigh = document.getElementById("status-high");
        const statusLow = document.getElementById("status-low");
        const statusClose = document.getElementById("status-close");
        const statusVolume = document.getElementById("status-volume");
        const statusRsi = document.getElementById("status-rsi");
        const statusObv = document.getElementById("status-obv");
        const cursorDateLabel = document.getElementById("cursor-date-label");
        const MIN_PANEL_HEIGHT = 120;
        const PANEL_FLEX_KEY = "chartPanelFlexState";
        const defaultPanelFlex = {
            price: 4.8,
            obv: 1.8,
            rsi: 1.8,
        };
        const chartPanels = Array.from(
            document.querySelectorAll(".chart-panel[data-panel-id]")
        );
        const panelResizers = document.querySelectorAll(".panel-resizer");
        let currentInterval = "1d";
        let currentDataset = null;
        let requestCounter = 0;
        let datasetList = [];
        let latestVolumeData = [];
        let latestCandles = [];
        let isVolumeVisible = true;
        const RECENT_CAPTURE_COUNT = 120;
        let candleMap = new Map();
        let volumeMap = new Map();
        let rsiMap = new Map();
        let obvMap = new Map();
        let latestTimeKey = null;
        const containerChartMap = new Map();
        let resizeObserverInstance = null;
        const observeChartContainer = (container, chart) => {
            if (!container || !chart) return;
            containerChartMap.set(container, chart);
            if (resizeObserverInstance) {
                resizeObserverInstance.observe(container);
            }
        };

        const hideCursorDateLabel = () => {
            if (!cursorDateLabel) return;
            cursorDateLabel.setAttribute("aria-hidden", "true");
        };

        const formatCursorDateText = (time) => {
            const date = businessDayToDate(time);
            if (!date) return "";
            const year = date.getUTCFullYear();
            const month = String(date.getUTCMonth() + 1).padStart(2, "0");
            const day = String(date.getUTCDate()).padStart(2, "0");
            return `${year}-${month}-${day}`;
        };

        const updateCursorDateLabel = (param) => {
            if (!cursorDateLabel || !priceContainer) return;
            if (!param || !param.time || !param.point) {
                hideCursorDateLabel();
                return;
            }
            const labelText = formatCursorDateText(param.time);
            if (!labelText) {
                hideCursorDateLabel();
                return;
            }
            cursorDateLabel.textContent = labelText;
            cursorDateLabel.setAttribute("aria-hidden", "false");
            const containerWidth = priceContainer.clientWidth;
            const halfWidth = (cursorDateLabel.offsetWidth || 0) / 2;
            const padding = 12;
            let targetX = param.point.x;
            const minX = padding + halfWidth;
            const maxX = containerWidth - halfWidth - padding;
            if (targetX < minX) targetX = minX;
            if (targetX > maxX) targetX = maxX;
            cursorDateLabel.style.left = `${targetX}px`;
        };

        const applySavedPanelFlexState = () => {
            if (!window?.localStorage) return;
            try {
                const stored = window.localStorage.getItem(PANEL_FLEX_KEY);
                if (!stored) return;
                const parsed = JSON.parse(stored);
                chartPanels.forEach((panel) => {
                    const key = panel.dataset.panelId;
                    const value = parsed?.[key];
                    if (typeof value === "number" && value > 0) {
                        panel.style.flexGrow = value;
                    }
                });
            } catch (error) {
                console.warn("패널 비율을 복원하지 못했습니다.", error);
            }
        };

        const persistPanelFlexState = () => {
            if (!window?.localStorage) return;
            try {
                const payload = {};
                chartPanels.forEach((panel) => {
                    const key = panel.dataset.panelId;
                    const flexGrow =
                        parseFloat(panel.style.flexGrow) ||
                        parseFloat(getComputedStyle(panel).flexGrow) ||
                        defaultPanelFlex[key] ||
                        1;
                    payload[key] = parseFloat(flexGrow.toFixed(3));
                });
                window.localStorage.setItem(
                    PANEL_FLEX_KEY,
                    JSON.stringify(payload)
                );
            } catch (error) {
                console.warn("패널 비율을 저장하지 못했습니다.", error);
            }
        };

        const enablePanelResizing = () => {
            panelResizers.forEach((resizer) => {
                resizer.addEventListener("pointerdown", (event) => {
                    const prevPanel = resizer.previousElementSibling;
                    const nextPanel = resizer.nextElementSibling;
                    if (
                        !prevPanel?.classList.contains("chart-panel") ||
                        !nextPanel?.classList.contains("chart-panel")
                    ) {
                        return;
                    }
                    event.preventDefault();
                    const pointerId = event.pointerId;
                    resizer.setPointerCapture?.(pointerId);
                    resizer.classList.add("dragging");
                    document.body.classList.add("panel-resize-active");
                    const startY = event.clientY;
                    const prevRect = prevPanel.getBoundingClientRect();
                    const nextRect = nextPanel.getBoundingClientRect();
                    const totalHeight = prevRect.height + nextRect.height;
                    const prevMin =
                        Number(prevPanel.dataset.minHeight) || MIN_PANEL_HEIGHT;
                    const nextMin =
                        Number(nextPanel.dataset.minHeight) || MIN_PANEL_HEIGHT;
                    const minTotal = prevMin + nextMin;
                    if (totalHeight <= minTotal) {
                        resizer.classList.remove("dragging");
                        document.body.classList.remove("panel-resize-active");
                        resizer.releasePointerCapture?.(pointerId);
                        return;
                    }
                    const maxPrev = totalHeight - nextMin;
                    const applySizes = (prevSize) => {
                        const clampedPrev = Math.max(
                            prevMin,
                            Math.min(maxPrev, prevSize)
                        );
                        const nextSize = totalHeight - clampedPrev;
                        prevPanel.style.flexGrow = clampedPrev;
                        nextPanel.style.flexGrow = nextSize;
                    };
                    const handlePointerMove = (moveEvent) => {
                        const delta = moveEvent.clientY - startY;
                        applySizes(prevRect.height + delta);
                    };
                    const stopResizing = () => {
                        resizer.classList.remove("dragging");
                        document.body.classList.remove("panel-resize-active");
                        window.removeEventListener(
                            "pointermove",
                            handlePointerMove
                        );
                        window.removeEventListener("pointerup", stopResizing);
                        resizer.releasePointerCapture?.(pointerId);
                        persistPanelFlexState();
                    };
                    window.addEventListener("pointermove", handlePointerMove);
                    window.addEventListener("pointerup", stopResizing, {
                        once: true,
                    });
                });
            });
        };

        applySavedPanelFlexState();
        enablePanelResizing();

        const businessDayToDate = (time) => {
            if (typeof time === "string") {
                const [year, month, day] = time.split("-").map(Number);
                return new Date(Date.UTC(year, month - 1, day));
            }
            if (typeof time === "number") {
                return new Date(time * 1000);
            }
            if (typeof time === "object" && "year" in time) {
                const { year, month, day } = time;
                return new Date(Date.UTC(year, month - 1, day));
            }
            return null;
        };

        const formatKoreanTick = (time, tickMarkType) => {
            const date = businessDayToDate(time);
            if (!date) return "";
            const month = date.getUTCMonth() + 1;
            const day = date.getUTCDate();
            const monthLabel = `${month}월`;
            switch (tickMarkType) {
                case LightweightCharts.TickMarkType.Year:
                    return `${date.getUTCFullYear()}년`;
                case LightweightCharts.TickMarkType.Month:
                    return monthLabel;
                case LightweightCharts.TickMarkType.Week:
                case LightweightCharts.TickMarkType.Day:
                case LightweightCharts.TickMarkType.Time: {
                    if (day === 1) {
                        if (month === 1) {
                            return `${date.getUTCFullYear()}년`;
                        }
                        return monthLabel;
                    }
                    return `${day}`;
                }
                default:
                    return `${month}/${day}`;
            }
        };

        const formatCompactNumber = (value) => {
            const abs = Math.abs(value);
            if (abs >= 1e12) return `${(value / 1e12).toFixed(2)}T`;
            if (abs >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
            if (abs >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
            if (abs >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
            return value.toFixed(2);
        };

        const baseOptions = {
            layout: {
                background: { color: "#000000" },
                textColor: "#f4f6ff",
                fontSize: 12,
                fontFamily: "Inter, Pretendard, sans-serif",
            },
            grid: {
                vertLines: { color: "rgba(0, 0, 0, 0)" },
                horzLines: { color: "rgba(0, 0, 0, 0)" },
            },
            crosshair: {
                mode: LightweightCharts.CrosshairMode.Normal,
                vertLine: {
                    width: 1,
                    color: "rgba(255, 255, 255, 0.4)",
                    labelBackgroundColor: "#1f2235",
                },
                horzLine: {
                    labelBackgroundColor: "#1f2235",
                },
            },
            rightPriceScale: {
                borderColor: "#1f2b4d",
                textColor: "#ffffff",
                visible: true,
            },
            timeScale: {
                borderColor: "#1f2b4d",
                textColor: "#d5ddff",
                ticksVisible: true,
                timeVisible: false,
                secondsVisible: false,
                rightOffset: 8,
                lockVisibleTimeRangeOnResize: true,
                tickMarkFormatter: formatKoreanTick,
            },
            localization: {
                locale: "ko-KR",
                dateFormat: "yyyy-MM-dd",
            },
        };

        const createChart = (container, overrides = {}) =>
            LightweightCharts.createChart(container, {
                ...baseOptions,
                width: container.clientWidth,
                height: container.clientHeight,
                ...overrides,
            });

        let priceChart, obvChart, rsiChart;
        let candleSeries, volumeSeries, rsiSeries, obvSeries;
        let latestObvData = [];
        let obvBaselineLine = null;
        let currentChartType = null;

        const destroyCharts = () => {
            if (resizeObserverInstance) {
                resizeObserverInstance.disconnect();
            }
            [priceChart, obvChart, rsiChart].forEach((chart) => {
                if (chart) {
                    chart.remove();
                }
            });
            priceContainer.innerHTML = "";
            obvContainer.innerHTML = "";
            rsiContainer.innerHTML = "";
            
            priceChart = null;
            obvChart = null;
            rsiChart = null;
            candleSeries = null;
            volumeSeries = null;
            rsiSeries = null;
            obvSeries = null;
            obvBaselineLine = null;
            latestObvData = [];
            obvBaselineLine = null;
            charts.length = 0;
            containerChartMap.clear();
            hideCursorDateLabel();
        };

        const initializeCharts = () => {
            priceChart = createChart(priceContainer);
            obvChart = createChart(obvContainer, {
                grid: {
                    vertLines: { color: "rgba(0, 0, 0, 0)" },
                    horzLines: { color: "rgba(0, 0, 0, 0)" },
                },
            });
            rsiChart = createChart(rsiContainer, {
                grid: {
                    vertLines: { color: "rgba(0, 0, 0, 0)" },
                    horzLines: { color: "rgba(0, 0, 0, 0)" },
                },
            });
            hideTimeAxis(priceChart);
            hideTimeAxis(obvChart);
            showTimeAxis(rsiChart);
            rsiChart.timeScale().applyOptions({
                borderColor: "rgba(31, 43, 77, 0.6)",
                textColor: "#cfd7fd",
                lockVisibleTimeRangeOnResize: true,
                tickMarkFormatter: formatKoreanTick,
                timeVisible: false,
                secondsVisible: false,
                ticksVisible: true,
            });

            priceChart.priceScale("right").applyOptions({
                textColor: "#ffffff",
                scaleMargins: {
                    top: 0.05,
                    bottom: 0.05,
                },
            });
            rsiChart.priceScale("right").applyOptions({
                textColor: "#ffffff",
                scaleMargins: {
                    top: 0.2,
                    bottom: 0.2,
                },
            });
            obvChart.priceScale("right").applyOptions({
                textColor: "#ffffff",
                scaleMargins: {
                    top: 0.2,
                    bottom: 0.2,
                },
            });

            candleSeries = priceChart.addCandlestickSeries({
                upColor: "#089981",
                downColor: "#f23645",
                wickUpColor: "#089981",
                wickDownColor: "#f23645",
                borderUpColor: "#089981",
                borderDownColor: "#f23645",
            });

            volumeSeries = priceChart.addHistogramSeries({
                priceScaleId: "left",
                base: 0,
                priceFormat: {
                    type: "volume",
                },
                priceLineVisible: false,
                color: "rgba(60, 120, 216, 0.5)",
                scaleMargins: {
                    top: 0.85,
                    bottom: 0,
                },
            });
            priceChart.priceScale("left").applyOptions({
                visible: false,
                scaleMargins: {
                    top: 0.85,
                    bottom: 0,
                },
            });

            rsiSeries = rsiChart.addLineSeries({
                color: "#ffffff",
                lineWidth: 3,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: true,
            });
            
            obvSeries = obvChart.addLineSeries({
                color: "#29b6f6",
                lineWidth: 3,
                priceLineVisible: false,
                lastValueVisible: false,
                crosshairMarkerVisible: true,
                priceFormat: {
                    type: "custom",
                    minMove: 0.01,
                    formatter: (price) => formatCompactNumber(price),
                },
            });

            if (obvBaselineLine) {
                obvSeries.removePriceLine(obvBaselineLine);
            }
            obvBaselineLine = obvSeries.createPriceLine({
                price: 0,
                color: "rgba(255, 255, 255, 0.3)",
                lineWidth: 1,
                lineStyle: LightweightCharts.LineStyle.Solid,
                axisLabelVisible: false,
            });

            obvChart.priceScale("right").applyOptions({
                mode: LightweightCharts.PriceScaleMode.Normal,
                autoScale: true,
                borderColor: "rgba(31, 43, 77, 0.7)",
                textColor: "#cfd7fd",
                scaleMargins: {
                    top: 0.2,
                    bottom: 0.2,
                },
            });

            const drawLevelLine = (price) =>
                rsiSeries.createPriceLine({
                    price,
                    color: "rgba(255, 255, 255, 0.25)",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Dashed,
                    axisLabelVisible: false,
                });

            drawLevelLine(70);
            drawLevelLine(30);

            registerChart(priceChart);
            registerChart(obvChart);
            registerChart(rsiChart);
            obvChart
                .timeScale()
                .subscribeVisibleLogicalRangeChange((range) => {
                    if (!range) return;
                    applyObvScale(range);
                });
            
            observeChartContainer(priceContainer, priceChart);
            observeChartContainer(obvContainer, obvChart);
            observeChartContainer(rsiContainer, rsiChart);

            const handleCrosshairMove = (param) => {
                if (!param || !param.time) {
                    updateStatusBar(null);
                    hideCursorDateLabel();
                    return;
                }
                const key = createTimeKey(param.time);
                updateStatusBar(key);
                updateCursorDateLabel(param);
            };
            [priceChart, obvChart, rsiChart].forEach((chart) => {
                chart?.subscribeCrosshairMove(handleCrosshairMove);
            });
        };

        const hideTimeAxis = (chart) => {
            if (!chart) return;
            chart.timeScale().applyOptions({
                visible: false,
                borderColor: "transparent",
                textColor: "transparent",
            });
        };
        const showTimeAxis = (chart) => {
            if (!chart) return;
            chart.timeScale().applyOptions({
                visible: true,
                borderColor: "#1f2b4d",
                textColor: "#9ba9cc",
                timeVisible: false,
                secondsVisible: false,
                ticksVisible: true,
                lockVisibleTimeRangeOnResize: true,
            });
        };
        hideTimeAxis(priceChart);
        hideTimeAxis(obvChart);
        showTimeAxis(rsiChart);
        if (rsiChart) {
            rsiChart.timeScale().applyOptions({
                borderColor: "rgba(31, 43, 77, 0.6)",
                textColor: "#cfd7fd",
                lockVisibleTimeRangeOnResize: true,
                tickMarkFormatter: formatKoreanTick,
            });
        }



        let syncing = false;

        const createTimeKey = (time) => {
            if (!time) return null;
            if (typeof time === "string") return time;
            if (typeof time === "number") {
                const date = new Date(time * 1000);
                const year = date.getUTCFullYear();
                const month = String(date.getUTCMonth() + 1).padStart(2, "0");
                const day = String(date.getUTCDate()).padStart(2, "0");
                return `${year}-${month}-${day}`;
            }
            if (typeof time === "object" && "year" in time) {
                const year = time.year ?? time.year;
                const month = String(time.month ?? time.month ?? 0).padStart(2, "0");
                const day = String(time.day ?? time.day ?? 0).padStart(2, "0");
                return `${year}-${month}-${day}`;
            }
            return null;
        };

        const buildDataMap = (series) => {
            const map = new Map();
            series.forEach((point) => {
                const key = createTimeKey(point.time);
                if (key) map.set(key, point);
            });
            return map;
        };

        const setDatasetMeta = (info) => {
        if (!info) {
            datasetMeta.textContent = "데이터셋 정보를 불러올 수 없습니다.";
            statusSymbol.textContent = "--";
            statusRange.textContent = "--";
            return;
        }
        datasetMeta.textContent = `${info.label} · ${info.range} · ${info.rows}건`;
        statusSymbol.textContent = info.label;
        statusRange.textContent = info.range;
    };

        const updateVolumeButton = () => {
            if (!volumeToggle) return;
            volumeToggle.classList.toggle("active", isVolumeVisible);
            volumeToggle.textContent = isVolumeVisible
                ? "거래량 표시"
                : "거래량 숨김";
        };

        const syncVolumeSeries = () => {
            if (!volumeSeries) return;
            if (isVolumeVisible) {
                volumeSeries.setData(latestVolumeData);
            } else {
                volumeSeries.setData([]);
            }
            volumeSeries.applyOptions({ visible: isVolumeVisible });
        };


        const formatNumber = (value, digits = 2) => {
            if (value === null || value === undefined || Number.isNaN(value)) {
                return "--";
            }
            return Number(value).toFixed(digits);
        };

        const formatVolumeValue = (value) => {
            if (!value && value !== 0) return "--";
            if (Math.abs(value) >= 1e9) return `${(value / 1e9).toFixed(2)}B`;
            if (Math.abs(value) >= 1e6) return `${(value / 1e6).toFixed(2)}M`;
            if (Math.abs(value) >= 1e3) return `${(value / 1e3).toFixed(2)}K`;
            return Number(value).toLocaleString("en-US");
        };

        const sleep = (ms = 0) =>
            new Promise((resolve) => setTimeout(resolve, ms));

        const updateStatusBar = (timeKey) => {
            const key = timeKey || latestTimeKey;
            const candle = key ? candleMap.get(key) : null;
            const volumePoint = key ? volumeMap.get(key) : null;
            const rsiPoint = key ? rsiMap.get(key) : null;
            const obvPoint = key ? obvMap.get(key) : null;
            statusDate.textContent = key ?? "--";
            statusOpen.textContent = candle ? formatNumber(candle.open) : "--";
            statusHigh.textContent = candle ? formatNumber(candle.high) : "--";
            statusLow.textContent = candle ? formatNumber(candle.low) : "--";
            statusClose.textContent = candle ? formatNumber(candle.close) : "--";
            statusVolume.textContent = volumePoint
                ? formatVolumeValue(volumePoint.value)
                : "--";
            statusRsi.textContent = rsiPoint
                ? formatNumber(rsiPoint.value, 2)
                : "--";
            statusObv.textContent = obvPoint
                ? formatVolumeValue(obvPoint.value)
                : "--";
        };

        const applyObvScale = (visibleRange = null) => {
            if (!obvSeries || !obvChart || !Array.isArray(latestObvData) || !latestObvData.length) {
                return;
            }

            let startIndex = 0;
            let endIndex = latestObvData.length - 1;
            if (
                visibleRange &&
                Number.isFinite(visibleRange.from) &&
                Number.isFinite(visibleRange.to)
            ) {
                startIndex = Math.max(0, Math.floor(visibleRange.from));
                endIndex = Math.min(latestObvData.length - 1, Math.ceil(visibleRange.to));
            }
            if (startIndex > endIndex) return;

            const segment = latestObvData.slice(startIndex, endIndex + 1);
            const values = segment
                .map((point) => point.value)
                .filter((value) => Number.isFinite(value));
            if (!values.length) return;

            const minValue = Math.min(...values);
            const maxValue = Math.max(...values);
            const span = Math.max(Math.abs(maxValue - minValue), 1);
            const padding = span * 0.1;
            const priceRange = {
                minValue: minValue - padding,
                maxValue: maxValue + padding,
            };

            obvSeries.applyOptions({
                autoscaleInfoProvider: () => ({ priceRange }),
            });

            obvChart.priceScale("right").applyOptions({
                autoScale: true,
                scaleMargins: {
                    top: 0.2,
                    bottom: 0.2,
                },
            });
            const priceScaleApi = obvChart.priceScale("right");
            if (priceScaleApi && typeof priceScaleApi.resetAutoScale === "function") {
                priceScaleApi.resetAutoScale();
            }
        };

        const charts = [];
        const subscribeChart = (chart) => {
            chart
                .timeScale()
                .subscribeVisibleLogicalRangeChange((range) =>
                    syncRanges(chart, range)
                );
        };

        const syncRanges = (sourceChart, range) => {
            if (!range || syncing) return;
            syncing = true;
            charts.forEach((chart) => {
                if (chart === sourceChart) return;
                chart.timeScale().setVisibleLogicalRange(range);
            });
            syncing = false;
        };



        const registerChart = (chart) => {
            if (!chart) return;
            charts.push(chart);
            subscribeChart(chart);
        };


        const setActiveIntervalButton = (interval) => {
            intervalButtons.forEach((button) => {
                const isActive = button.dataset.interval === interval;
                button.classList.toggle("active", isActive);
                button.disabled = isActive;
            });
        };

        const loadInterval = async (interval, dataset = currentDataset) => {
            if (!dataset) return;
            const token = ++requestCounter;
            setActiveIntervalButton(interval);
            try {
                const url = new URL("/api/candles", window.location.origin);
                url.searchParams.set("interval", interval);
                url.searchParams.set("dataset", dataset);
                const response = await fetch(url);
                if (!response.ok) {
                    let message = "차트 데이터를 불러오지 못했습니다.";
                    try {
                        const payload = await response.json();
                        if (payload?.detail) message = payload.detail;
                    } catch (_) {
                        // ignore JSON parse errors
                    }
                    throw new Error(message);
                }
                const data = await response.json();
                if (token !== requestCounter) return;

                if (data.type && data.type !== currentChartType) {
                    destroyCharts();
                    initializeCharts();
                    currentChartType = data.type;
                } else if (!priceChart) {
                    initializeCharts();
                    currentChartType = data.type || "stock";
                }

                candleSeries.setData(data.candles);
                latestVolumeData = data.volumes;
                latestCandles = data.candles;
                latestObvData = data.obv || [];
                candleMap = buildDataMap(data.candles);
                volumeMap = buildDataMap(data.volumes);
                rsiMap = buildDataMap(data.rsi);
                obvMap = buildDataMap(data.obv);
                const lastCandle = data.candles[data.candles.length - 1];
                latestTimeKey = lastCandle ? createTimeKey(lastCandle.time) : null;
                syncVolumeSeries();
                rsiSeries.setData(data.rsi);
                obvSeries.setData(data.obv);
                if (obvBaselineLine) {
                    obvSeries.removePriceLine(obvBaselineLine);
                }
                obvBaselineLine = obvSeries.createPriceLine({
                    price: 0,
                    color: "rgba(255, 255, 255, 0.3)",
                    lineWidth: 1,
                    lineStyle: LightweightCharts.LineStyle.Solid,
                    axisLabelVisible: false,
                });
                const range = obvChart.timeScale().getVisibleLogicalRange();
                applyObvScale(range);
                applyObvScale(data.obv);
                priceChart.timeScale().fitContent();
                const syncedRange = priceChart.timeScale().getVisibleLogicalRange();
                syncRanges(priceChart, syncedRange);
                currentInterval = interval;
                currentDataset = dataset;
                updateStatusBar(latestTimeKey);
            } catch (error) {
                if (token === requestCounter) {
                    setActiveIntervalButton(currentInterval);
                }
                console.error(error);
                alert(error.message || "차트 데이터를 불러오지 못했습니다.");
            }
        };

        const focusRecentCandles = async (count) => {
            if (
                !count ||
                !priceChart ||
                !priceChart.timeScale ||
                !latestCandles.length
            ) {
                return null;
            }
            const startIndex = Math.max(0, latestCandles.length - count);
            const from = latestCandles[startIndex]?.time;
            const to = latestCandles[latestCandles.length - 1]?.time;
            if (from === undefined || to === undefined) {
                return null;
            }
            const previousRange = priceChart.timeScale().getVisibleRange();
            priceChart.timeScale().setVisibleRange({ from, to });
            await sleep(120);
            return () => {
                if (previousRange) {
                    priceChart.timeScale().setVisibleRange(previousRange);
                }
            };
        };

        const copyChartScreenshotToClipboard = async (options = {}) => {
            const captureChartCanvas = (chartInstance) => {
                if (
                    chartInstance &&
                    typeof chartInstance.takeScreenshot === "function"
                ) {
                    return chartInstance.takeScreenshot();
                }
                return null;
            };

            const gatherScreenshots = () => {
                const shots = [];
                [priceChart, obvChart, rsiChart].forEach(
                    (chart) => {
                        const canvas = captureChartCanvas(chart);
                        if (canvas) shots.push(canvas);
                    }
                );
                return shots;
            };

            const composeStackedCanvas = (segments) => {
                if (!segments.length) return null;
                const width = Math.max(...segments.map((c) => c.width));
                const height = segments.reduce((sum, c) => sum + c.height, 0);
                const merged = document.createElement("canvas");
                merged.width = width;
                merged.height = height;
                const ctx = merged.getContext("2d");
                let offsetY = 0;
                segments.forEach((segment) => {
                    const offsetX = (width - segment.width) / 2;
                    ctx.drawImage(segment, offsetX, offsetY);
                    offsetY += segment.height;
                });
                return merged;
            };

            let restoreRange = null;
            try {
                if (options?.recentCandles) {
                    restoreRange = await focusRecentCandles(
                        options.recentCandles
                    );
                }
                const segments = gatherScreenshots();
                if (!segments.length) {
                    alert(
                        "차트를 아직 불러오고 있습니다. 잠시 후 다시 시도해 주세요."
                    );
                    return;
                }
                const canvas = composeStackedCanvas(segments);
                if (!canvas) throw new Error("스크린샷 생성에 실패했습니다.");
                const blob = await new Promise((resolve, reject) => {
                    canvas.toBlob((result) => {
                        if (result) resolve(result);
                        else reject(new Error("이미지 변환에 실패했습니다."));
                    }, "image/png");
                });
                if (navigator.clipboard?.write && window.ClipboardItem) {
                    const item = new ClipboardItem({ "image/png": blob });
                    await navigator.clipboard.write([item]);
                    console.info("차트 이미지를 클립보드에 복사했습니다.");
                } else {
                    const url = URL.createObjectURL(blob);
                    const link = document.createElement("a");
                    link.href = url;
                    link.download = `chart-${Date.now()}.png`;
                    document.body.appendChild(link);
                    link.click();
                    document.body.removeChild(link);
                    URL.revokeObjectURL(url);
                }
            } catch (error) {
                console.error(error);
                alert("차트 이미지를 복사하지 못했습니다.");
            } finally {
                if (restoreRange) {
                    await sleep(60);
                    restoreRange();
                }
            }
        };

        intervalButtons.forEach((button) => {
            button.addEventListener("click", () => {
                const interval = button.dataset.interval;
                if (!interval || interval === currentInterval) return;
                loadInterval(interval, currentDataset);
            });
        });

        const populateDatasetSelect = (items) => {
            datasetSelect.innerHTML = "";
            items.forEach((item) => {
                const option = document.createElement("option");
                option.value = item.id;
                option.textContent = `${item.label} · ${item.range}`;
                datasetSelect.appendChild(option);
            });
            datasetSelect.disabled = items.length === 0;
        };

        const bootstrapDatasets = async () => {
            try {
                const response = await fetch("/api/datasets");
                if (!response.ok) {
                    throw new Error("데이터셋 목록을 불러오지 못했습니다.");
                }
                const data = await response.json();
                datasetList = data;
                populateDatasetSelect(data);
                const fallback = data.find((item) => item.default) ?? data[0];
                if (!fallback) {
                    setDatasetMeta(null);
                    return;
                }
                currentDataset = fallback.id;
                datasetSelect.value = currentDataset;
                setDatasetMeta(fallback);
                await loadInterval(currentInterval, currentDataset);
            } catch (error) {
                console.error(error);
                alert(error.message || "데이터셋 목록을 불러오지 못했습니다.");
                setDatasetMeta(null);
            }
        };

        datasetSelect.addEventListener("change", () => {
            const selected = datasetSelect.value;
            if (!selected || selected === currentDataset) return;
            currentDataset = selected;
            const meta = datasetList.find((item) => item.id === selected);
            setDatasetMeta(meta ?? null);
            loadInterval(currentInterval, currentDataset);
        });

        if (volumeToggle) {
            volumeToggle.addEventListener("click", () => {
                isVolumeVisible = !isVolumeVisible;
                updateVolumeButton();
                syncVolumeSeries();
            });
        }

        setActiveIntervalButton(currentInterval);
        updateVolumeButton();

        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const chart = containerChartMap.get(entry.target);
                if (!chart) continue;
                const { width, height } = entry.contentRect;
                chart.applyOptions({ width, height });
            }
        });
        resizeObserverInstance = resizeObserver;

        bootstrapDatasets();

        document.addEventListener("keydown", (event) => {
            if (
                (event.key === "S" || event.key === "s") &&
                event.ctrlKey &&
                event.shiftKey
            ) {
                event.preventDefault();
                copyChartScreenshotToClipboard();
            }
            if (
                (event.key === "X" || event.key === "x") &&
                event.ctrlKey &&
                event.shiftKey
            ) {
                event.preventDefault();
                copyChartScreenshotToClipboard({
                    recentCandles: RECENT_CAPTURE_COUNT,
                });
            }
        });
    </script>
</body>
</html>
        """
    return (
        template.replace("%(up)s", UP_COLOR)
        .replace("%(down)s", DOWN_COLOR)
        .replace("%(rsi)s", RSI_COLOR)
        .replace("%(obv)s", OBV_COLOR)
    )


def main() -> None:
    uvicorn.run(
        "main:app",
        host="127.0.0.1",
        port=8000,
        reload=True,
    )


if __name__ == "__main__":
    main()
