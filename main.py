from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List, Optional

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
OBV_COLOR = "#f5a623"
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
def _build_payload(dataset_id: str, normalized_interval: str) -> Dict[str, List[Dict]]:
    base_data = get_price_data(dataset_id)
    working = resample_price_data(base_data, normalized_interval)
    return format_chart_payload(working)


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


def format_chart_payload(data: pd.DataFrame) -> Dict[str, List[Dict]]:
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
        time_payload = {
            "year": int(timestamp.year),
            "month": int(timestamp.month),
            "day": int(timestamp.day),
        }
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
) -> Dict[str, List[Dict]]:
    try:
        normalized_interval = normalize_interval(interval)
        dataset_id = normalize_dataset_id(dataset)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        return _build_payload(dataset_id, normalized_interval)
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
        body {
            margin: 0;
            font-family: "Pretendard", "Inter", system-ui, -apple-system, BlinkMacSystemFont, sans-serif;
            background-color: #000000;
            color: #c7cfde;
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
            height: calc(100vh - 86px);
            padding: 0 1.5rem 1.5rem;
        }
        .chart-stack {
            display: flex;
            flex-direction: column;
            gap: 0.65rem;
            height: 100%;
        }
        .chart-panel {
            flex: 1;
            min-height: 120px;
            background: #000000;
            border: 1px solid #161a28;
            border-radius: 10px;
            box-shadow: inset 0 0 30px rgba(0, 0, 0, 0.6);
        }
        .chart-panel.price {
            flex: 4.8;
        }
        .chart-panel.obv {
            flex: 1.8;
        }
        .chart-panel.rsi {
            flex: 1.8;
            padding-bottom: 0.35rem;
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
            <button type="button" id="volume-toggle" class="pill-button active">거래량 표시</button>
            <div class="interval-toggle" role="group" aria-label="차트 주기 선택">
                <button type="button" class="interval-button active" data-interval="1d">1일</button>
                <button type="button" class="interval-button" data-interval="3d">3일</button>
                <button type="button" class="interval-button" data-interval="1w">1주</button>
            </div>
        </div>
    </header>
    <main>
        <div class="chart-stack">
            <div id="price-chart" class="chart-panel price"></div>
            <div id="obv-chart" class="chart-panel obv"></div>
            <div id="rsi-chart" class="chart-panel rsi"></div>
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
        let currentInterval = "1d";
        let currentDataset = null;
        let requestCounter = 0;
        let datasetList = [];
        let latestVolumeData = [];
        let isVolumeVisible = true;

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
            switch (tickMarkType) {
                case LightweightCharts.TickMarkType.Year:
                    return `${date.getUTCFullYear()}년`;
                case LightweightCharts.TickMarkType.Month:
                    return `${month}월`;
                case LightweightCharts.TickMarkType.Week:
                case LightweightCharts.TickMarkType.Day:
                case LightweightCharts.TickMarkType.Time: {
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
                textColor: "#a5afce",
                fontSize: 12,
                fontFamily: "Inter, Pretendard, sans-serif",
            },
            grid: {
                vertLines: { color: "rgba(30, 36, 54, 0.6)" },
                horzLines: { color: "rgba(30, 36, 54, 0.4)" },
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
            },
            timeScale: {
                borderColor: "#1f2b4d",
                textColor: "#9ba9cc",
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

        const priceChart = createChart(priceContainer);
        const obvChart = createChart(obvContainer, {
            grid: {
                vertLines: { color: "rgba(30, 36, 54, 0.45)" },
                horzLines: { color: "rgba(30, 36, 54, 0.3)" },
            },
        });
        const rsiChart = createChart(rsiContainer, {
            grid: {
                vertLines: { color: "rgba(30, 36, 54, 0.45)" },
                horzLines: { color: "rgba(30, 36, 54, 0.3)" },
            },
        });

        const hideTimeAxis = (chart) =>
            chart.timeScale().applyOptions({
                visible: false,
                borderColor: "transparent",
                textColor: "transparent",
            });
        const showTimeAxis = (chart) =>
            chart.timeScale().applyOptions({
                visible: true,
                borderColor: "#1f2b4d",
                textColor: "#9ba9cc",
                timeVisible: false,
                secondsVisible: false,
                ticksVisible: true,
                lockVisibleTimeRangeOnResize: true,
            });
        hideTimeAxis(priceChart);
        hideTimeAxis(obvChart);
        showTimeAxis(rsiChart);

        priceChart.priceScale("right").applyOptions({
            scaleMargins: {
                top: 0.05,
                bottom: 0.05,
            },
        });
        rsiChart.priceScale("right").applyOptions({
            scaleMargins: {
                top: 0.2,
                bottom: 0.2,
            },
        });
        obvChart.priceScale("right").applyOptions({
            scaleMargins: {
                top: 0.2,
                bottom: 0.2,
            },
        });

        const candleSeries = priceChart.addCandlestickSeries({
            upColor: "%(up)s",
            downColor: "%(down)s",
            wickUpColor: "%(up)s",
            wickDownColor: "%(down)s",
            borderUpColor: "%(up)s",
            borderDownColor: "%(down)s",
        });

        const volumeSeries = priceChart.addHistogramSeries({
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

        const rsiSeries = rsiChart.addLineSeries({
            color: "%(rsi)s",
            lineWidth: 2,
            priceLineVisible: false,
            lastValueVisible: false,
            crosshairMarkerVisible: true,
        });
        const obvSeries = obvChart.addLineSeries({
            color: "%(obv)s",
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

        obvChart.priceScale("right").applyOptions({
            mode: LightweightCharts.PriceScaleMode.Normal,
            autoScale: true,
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

        const charts = [priceChart, obvChart, rsiChart];
        let syncing = false;

        const setDatasetMeta = (info) => {
            if (!info) {
                datasetMeta.textContent = "데이터셋 정보를 불러올 수 없습니다.";
                return;
            }
            datasetMeta.textContent = `${info.label} · ${info.range} · ${info.rows}건`;
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

        const syncRanges = (sourceChart, range) => {
            if (!range || syncing) return;
            syncing = true;
            charts.forEach((chart) => {
                if (chart === sourceChart) return;
                chart.timeScale().setVisibleLogicalRange(range);
            });
            syncing = false;
        };

        charts.forEach((chart) => {
            chart
                .timeScale()
                .subscribeVisibleLogicalRangeChange((range) =>
                    syncRanges(chart, range)
                );
        });

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
                candleSeries.setData(data.candles);
                latestVolumeData = data.volumes;
                syncVolumeSeries();
                rsiSeries.setData(data.rsi);
                obvSeries.setData(data.obv);
                priceChart.timeScale().fitContent();
                const syncedRange = priceChart.timeScale().getVisibleLogicalRange();
                syncRanges(priceChart, syncedRange);
                currentInterval = interval;
                currentDataset = dataset;
            } catch (error) {
                if (token === requestCounter) {
                    setActiveIntervalButton(currentInterval);
                }
                console.error(error);
                alert(error.message || "차트 데이터를 불러오지 못했습니다.");
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
        bootstrapDatasets();

        const containerChartMap = new Map([
            [priceContainer, priceChart],
            [obvContainer, obvChart],
            [rsiContainer, rsiChart],
        ]);

        const resizeObserver = new ResizeObserver((entries) => {
            for (const entry of entries) {
                const chart = containerChartMap.get(entry.target);
                if (!chart) continue;
                const { width, height } = entry.contentRect;
                chart.applyOptions({ width, height });
            }
        });
        containerChartMap.forEach((_, container) =>
            resizeObserver.observe(container)
        );
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
