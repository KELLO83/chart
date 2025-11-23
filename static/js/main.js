const priceContainer = document.getElementById("price-chart");
const rsiContainer = document.getElementById("rsi-chart");
const obvContainer = document.getElementById("obv-chart");
const timeAxisContainer = document.getElementById("time-axis-chart");
const cvdContainer = document.getElementById("cvd-chart");
const cvdModal = document.getElementById("cvd-modal");
const cvdClose = document.getElementById("cvd-close");
const cvdMeta = document.getElementById("cvd-meta");
const cvdTableWrapper = document.querySelector(".cvd-table-wrapper");
const cvdTableHeader = document.getElementById("cvd-table-header");
const cvdTableBody = document.getElementById("cvd-table");
const datasetSelect = document.getElementById("dataset-select");
const datasetMeta = document.getElementById("dataset-meta");
const intervalButtons = document.querySelectorAll(
    ".interval-toggle .interval-button"
);
const cvdToggle = document.getElementById("cvd-toggle");
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
let currentInterval = "1d";
let currentDataset = null;
let requestCounter = 0;
let datasetList = [];
let latestVolumeData = [];
let isVolumeVisible = true;
let cvdChart = null;
let cvdSeries = null;
let cvdDataCache = null;
let cvdTableData = null;
let cvdAvailable = false;
let cvdModalVisible = false;
let candleMap = new Map();
let volumeMap = new Map();
let rsiMap = new Map();
let obvMap = new Map();
let latestTimeKey = null;
let currentHoverLogical = null;
const containerChartMap = new Map();
let resizeObserverInstance = null;
const defaultCvdColumns = [
    { key: "개인", label: "개인" },
    { key: "외국인", label: "외국인" },
    { key: "금융투자", label: "금융투자" },
    { key: "투자신탁", label: "투자신탁" },
    { key: "사모펀드", label: "사모펀드" },
    { key: "보험", label: "보험" },
    { key: "은행", label: "은행" },
    { key: "연기금", label: "연기금" },
    { key: "기타법인", label: "기타법인" },
    { key: "기타기관", label: "기타기관" },
];
const observeChartContainer = (container, chart) => {
    if (!container || !chart) return;
    containerChartMap.set(container, chart);
    if (resizeObserverInstance) {
        resizeObserverInstance.observe(container);
    }
};

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

const updateCvdTableTemplate = (columnCount) => {
    if (!cvdTableWrapper) return;
    const safeCount = Math.max(columnCount, 1);
    const template = `120px repeat(${safeCount}, minmax(90px, 1fr))`;
    cvdTableWrapper.style.setProperty("--cvd-table-template", template);
};
const clamp = (value, min, max) => Math.max(min, Math.min(max, value));
const resetPriceScale = () => {
    if (!priceChart) return;
    const timeScale = priceChart.timeScale();
    if (timeScale.resetTimeScale) {
        timeScale.resetTimeScale();
    } else {
        timeScale.fitContent();
    }
    alignChartsToLatest();
    priceChart.priceScale("right").applyOptions({
        autoScale: true,
        scaleMargins: {
            top: 0.05,
            bottom: 0.05,
        },
    });
};
const zoomContainers = [];
const registerZoomContainer = (container) => {
    if (container) zoomContainers.push(container);
};
const resolvePointerXOnPriceChart = (event) => {
    if (priceContainer) {
        const baseRect = priceContainer.getBoundingClientRect?.();
        if (baseRect && baseRect.width > 0) {
            return clamp(event.clientX - baseRect.left, 0, baseRect.width);
        }
    }
    const fallbackRect = event.currentTarget?.getBoundingClientRect?.();
    if (fallbackRect && fallbackRect.width > 0) {
        return clamp(event.clientX - fallbackRect.left, 0, fallbackRect.width);
    }
    return null;
};
const handleWheelZoom = (event) => {
    if (!priceChart) return;
    const range = priceChart.timeScale().getVisibleLogicalRange();
    if (!range) return;
    event.preventDefault();
    event.stopPropagation();
    event.stopImmediatePropagation?.();
    const direction = event.deltaY < 0 ? 1 : -1; // up -> zoom in
    const zoomIntensity = 0.22;
    const currentWidth = range.to - range.from;
    const minWidth = 8;
    const maxWidth = Math.max(currentWidth * 4, 1200);
    const factor = direction > 0 ? 1 - zoomIntensity : 1 + zoomIntensity;
    const newWidth = clamp(currentWidth * factor, minWidth, maxWidth);
    const pointerX = resolvePointerXOnPriceChart(event);
    const pointerLogical =
        typeof pointerX === "number"
            ? priceChart.timeScale().coordinateToLogical(pointerX)
            : null;
    let anchorLogical = null;
    if (typeof pointerLogical === "number") {
        anchorLogical = pointerLogical;
    } else if (typeof currentHoverLogical === "number") {
        anchorLogical = currentHoverLogical;
    } else {
        anchorLogical = range.from + currentWidth / 2;
    }
    const anchorOffset = clamp(
        anchorLogical - range.from,
        0,
        currentWidth
    );
    const anchorRatio = anchorOffset / currentWidth || 0.5;
    const newFrom = anchorLogical - newWidth * anchorRatio;
    const newTo = newFrom + newWidth;
    priceChart.timeScale().setVisibleLogicalRange({ from: newFrom, to: newTo });
    if (typeof pointerX === "number") {
        requestAnimationFrame(() => {
            const adjustedRange = priceChart.timeScale().getVisibleLogicalRange();
            const adjustedLogical = priceChart
                .timeScale()
                .coordinateToLogical(pointerX);
            if (
                !adjustedRange ||
                typeof anchorLogical !== "number" ||
                typeof adjustedLogical !== "number"
            ) {
                return;
            }
            const logicalDelta = adjustedLogical - anchorLogical;
            if (Math.abs(logicalDelta) < 1e-3) return;
            priceChart.timeScale().setVisibleLogicalRange({
                from: adjustedRange.from - logicalDelta,
                to: adjustedRange.to - logicalDelta,
            });
        });
    }
};
const priceAxisDoubleClickThreshold = 110;
const handlePriceAxisDoubleClick = (event) => {
    if (!priceContainer) return;
    const rect = priceContainer.getBoundingClientRect();
    const offsetX = event.clientX - rect.left;
    const distanceFromRight = rect.width - offsetX;
    if (distanceFromRight > priceAxisDoubleClickThreshold) {
        return;
    }
    event.preventDefault();
    resetPriceScale();
};

const baseOptions = {
    layout: {
        background: { color: "#000000" },
        textColor: "#f4f6ff",
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
const timeAxisChart = timeAxisContainer
    ? createChart(timeAxisContainer, {
          layout: {
              background: { color: "rgba(0, 0, 0, 0)" },
              textColor: "#dfe4ff",
              fontFamily:
                  '"JetBrains Mono", "Roboto Mono", "Inter", sans-serif',
              fontSize: 11,
          },
          grid: {
              vertLines: { color: "rgba(0, 0, 0, 0)" },
              horzLines: { color: "rgba(0, 0, 0, 0)" },
          },
          crosshair: {
              mode: LightweightCharts.CrosshairMode.Hidden,
          },
          handleScroll: false,
          handleScale: false,
          leftPriceScale: { visible: false },
          rightPriceScale: { visible: false },
          timeScale: {
              borderColor: "rgba(31, 43, 77, 0.6)",
              textColor: "#dfe4ff",
              lockVisibleTimeRangeOnResize: true,
              ticksVisible: true,
              timeVisible: false,
              secondsVisible: false,
              rightOffset: 8,
              tickMarkFormatter: formatKoreanTick,
          },
      })
    : null;
const timeAxisSeries = timeAxisChart
    ? timeAxisChart.addLineSeries({
          color: "rgba(0,0,0,0)",
          lineWidth: 0,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
      })
    : null;

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
if (timeAxisChart) {
    timeAxisChart.priceScale("right").applyOptions({
        visible: false,
    });
    timeAxisChart.timeScale().applyOptions({
        visible: true,
        borderColor: "rgba(31, 43, 77, 0.6)",
        textColor: "#cfd7fd",
        lockVisibleTimeRangeOnResize: true,
        tickMarkFormatter: formatKoreanTick,
    });
}

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

const candleSeries = priceChart.addCandlestickSeries({
    upColor: "#089981",
    downColor: "#f23645",
    wickUpColor: "#089981",
    wickDownColor: "#f23645",
    borderUpColor: "#089981",
    borderDownColor: "#f23645",
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
    color: "#f5a623",
    lineWidth: 2,
    priceLineVisible: false,
    lastValueVisible: false,
    crosshairMarkerVisible: true,
});
const obvSeries = obvChart.addLineSeries({
    color: "#f5a623",
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

let syncing = false;

const createTimeKey = (time) => {
    if (!time) return null;
    if (typeof time === "string") return time;
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
        if (cvdMeta) {
            cvdMeta.textContent = "수급 데이터 없음";
        }
        return;
    }
    datasetMeta.textContent = `${info.label} · ${info.range} · ${info.rows}건`;
    statusSymbol.textContent = info.label;
    statusRange.textContent = info.range;
    if (cvdMeta) {
        cvdMeta.textContent = info.cvd
            ? `${info.label} · ${info.range}`
            : "수급 데이터 없음";
    }
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

const updateCvdButtonState = () => {
    if (!cvdToggle) return;
    if (!cvdAvailable) {
        cvdToggle.disabled = true;
        cvdToggle.classList.remove("active");
        cvdToggle.textContent = "수급분석 없음";
        return;
    }
    cvdToggle.disabled = false;
    cvdToggle.classList.remove("active");
    cvdToggle.textContent = "수급분석";
};

const ensureCvdChart = () => {
    if (cvdChart || !cvdContainer) return;
    cvdChart = createChart(cvdContainer, {
        grid: {
            vertLines: { color: "rgba(30, 36, 54, 0.45)" },
            horzLines: { color: "rgba(30, 36, 54, 0.3)" },
        },
    });
    cvdChart.priceScale("right").applyOptions({
        textColor: "#ffffff",
        scaleMargins: { top: 0.2, bottom: 0.2 },
    });
    cvdSeries = {
        institutions: cvdChart.addLineSeries({
            color: "#ff8c5a",
            lineWidth: 2,
            priceLineVisible: false,
            crosshairMarkerVisible: true,
        }),
        foreigners: cvdChart.addLineSeries({
            color: "#00c8ff",
            lineWidth: 2,
            priceLineVisible: false,
            crosshairMarkerVisible: true,
        }),
        individuals: cvdChart.addLineSeries({
            color: "#f5e663",
            lineWidth: 2,
            priceLineVisible: false,
            crosshairMarkerVisible: true,
        }),
    };
    registerChart(cvdChart);
    observeChartContainer(cvdContainer, cvdChart);
};

const accumulateCvdSeries = (series) => {
    const entries = new Map();
    const roles = ["institutions", "individuals", "foreigners"];
    const ensureEntry = (point) => {
        const keyStr = createTimeKey(point.time);
        if (!keyStr) return null;
        if (!entries.has(keyStr)) {
            entries.set(keyStr, { time: point.time });
        }
        return { key: keyStr, entry: entries.get(keyStr) };
    };
    roles.forEach((role) => {
        (series[role] ?? []).forEach((point) => {
            const ensured = ensureEntry(point);
            if (!ensured) return;
            ensured.entry[role] =
                (ensured.entry[role] ?? 0) + Number(point.value || 0);
        });
    });
    const sorted = Array.from(entries.entries()).sort(([a], [b]) =>
        a.localeCompare(b)
    );
    const totals = {
        institutions: 0,
        individuals: 0,
        foreigners: 0,
    };
    const accumulatedSeries = {
        institutions: [],
        individuals: [],
        foreigners: [],
    };
    const rows = [];
    sorted.forEach(([dateKey, entry]) => {
        roles.forEach((role) => {
            const delta = entry[role] ?? 0;
            totals[role] += delta;
            accumulatedSeries[role].push({
                time: entry.time,
                value: totals[role],
            });
        });
        rows.push({
            date: dateKey,
            institutions: totals.institutions,
            individuals: totals.individuals,
            foreigners: totals.foreigners,
        });
    });
    return {
        series: accumulatedSeries,
        rows: rows.reverse(),
    };
};

const formatSigned = (value) => {
    if (value === null || value === undefined || Number.isNaN(value)) {
        return { text: "--", cls: "" };
    }
    const numeric = Number(value);
    const rounded = Math.round(numeric);
    const absFormatted = Math.abs(rounded).toLocaleString("ko-KR");
    const text =
        rounded === 0
            ? "0"
            : `${rounded > 0 ? "+" : "-"}${absFormatted}`;
    const cls =
        rounded > 0 ? "cvd-positive" : rounded < 0 ? "cvd-negative" : "";
    return { text, cls };
};

const renderCvdTable = (tableData) => {
    if (!cvdTableBody || !cvdTableHeader) return;
    const columns =
        tableData?.columns?.length > 0
            ? tableData.columns
            : defaultCvdColumns;
    updateCvdTableTemplate(columns.length);
    const headerHtml = [
        "<span>일자</span>",
        ...columns.map((col) => `<span>${col.label}</span>`),
    ].join("");
    cvdTableHeader.innerHTML = headerHtml;
    const rows = tableData?.rows ?? [];
    if (!rows.length) {
        cvdTableBody.innerHTML =
            '<div class="cvd-table-row empty"><span>데이터 없음</span></div>';
        return;
    }
    const html = rows
        .map((row, index) => {
            const rowClass =
                index === 0 && row.date === "합계"
                    ? "cvd-table-row summary"
                    : "cvd-table-row";
            const cells = [
                `<span>${row.date}</span>`,
                ...columns.map((col) => {
                    const { text, cls } = formatSigned(row[col.key]);
                    return `<span class="${cls}">${text}</span>`;
                }),
            ];
            return `<div class="${rowClass}">${cells.join("")}</div>`;
        })
        .join("");
    cvdTableBody.innerHTML = html;
};

const applyCvdSeriesData = (seriesData) => {
    if (!seriesData) return;
    ensureCvdChart();
    if (!cvdSeries) return;
    const accumulated = accumulateCvdSeries(seriesData);
    cvdSeries.institutions.setData(accumulated.series.institutions ?? []);
    cvdSeries.foreigners.setData(accumulated.series.foreigners ?? []);
    cvdSeries.individuals.setData(accumulated.series.individuals ?? []);
    renderCvdTable(accumulated.rows);
    if (cvdModalVisible && cvdChart) {
        cvdChart.timeScale().fitContent();
    }
};

const openCvdModal = () => {
    if (!cvdAvailable || !cvdModal) return;
    if (cvdDataCache) {
        ensureCvdChart();
    }
    cvdModal.classList.add("visible");
    document.body.classList.add("modal-open");
    cvdModalVisible = true;
    cvdToggle?.classList.add("active");
    if (cvdChart && cvdDataCache) {
        cvdChart.timeScale().fitContent();
    }
};

const closeCvdModal = () => {
    if (!cvdModalVisible || !cvdModal) return;
    cvdModal.classList.remove("visible");
    document.body.classList.remove("modal-open");
    cvdModalVisible = false;
    cvdToggle?.classList.remove("active");
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

const charts = [priceChart, obvChart, rsiChart, timeAxisChart].filter(
    Boolean
);
const alignChartsToLatest = () => {
    charts.forEach((chart) => {
        chart.timeScale().scrollToRealTime();
    });
};
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

charts.forEach(subscribeChart);

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
    currentHoverLogical = null;
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
        if (timeAxisSeries) {
            timeAxisSeries.setData(
                data.candles.map((point) => ({
                    time: point.time,
                    value: 0,
                }))
            );
        }
        latestVolumeData = data.volumes;
        candleMap = buildDataMap(data.candles);
        volumeMap = buildDataMap(data.volumes);
        rsiMap = buildDataMap(data.rsi);
        obvMap = buildDataMap(data.obv);
        const lastCandle = data.candles[data.candles.length - 1];
        latestTimeKey = lastCandle ? createTimeKey(lastCandle.time) : null;
        const cvdPayload = data.cvd ?? null;
        cvdDataCache = cvdPayload?.series ?? null;
        cvdTableData = cvdPayload?.table ?? null;
        const hasTableData = Boolean(cvdTableData?.rows?.length);
        cvdAvailable = Boolean(cvdDataCache || hasTableData);
        if (cvdDataCache) {
            applyCvdSeriesData(cvdDataCache);
        } else if (!hasTableData) {
            closeCvdModal();
        }
        renderCvdTable(cvdTableData);
        updateCvdButtonState();
        syncVolumeSeries();
        rsiSeries.setData(data.rsi);
        obvSeries.setData(data.obv);
        priceChart.timeScale().applyOptions({ rightOffset: 8 });
        priceChart.timeScale().fitContent();
        const syncedRange = priceChart.timeScale().getVisibleLogicalRange();
        syncRanges(priceChart, syncedRange);
        alignChartsToLatest();
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
        cvdAvailable = Boolean(fallback.cvd);
        cvdDataCache = null;
        cvdTableData = null;
        closeCvdModal();
        updateCvdButtonState();
        renderCvdTable(null);
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
    currentHoverLogical = null;
    currentDataset = selected;
    const meta = datasetList.find((item) => item.id === selected);
    setDatasetMeta(meta ?? null);
    cvdAvailable = Boolean(meta?.cvd);
    cvdDataCache = null;
    cvdTableData = null;
    closeCvdModal();
    updateCvdButtonState();
    renderCvdTable(null);
    loadInterval(currentInterval, currentDataset);
});

if (volumeToggle) {
    volumeToggle.addEventListener("click", () => {
        isVolumeVisible = !isVolumeVisible;
        updateVolumeButton();
        syncVolumeSeries();
    });
}

if (cvdToggle) {
    cvdToggle.addEventListener("click", () => {
        if (!cvdAvailable) return;
        if (cvdModalVisible) {
            closeCvdModal();
        } else {
            openCvdModal();
        }
    });
}

if (cvdClose) {
    cvdClose.addEventListener("click", closeCvdModal);
}
if (cvdModal) {
    cvdModal.addEventListener("click", (event) => {
        if (event.target === cvdModal) {
            closeCvdModal();
        }
    });
}

priceChart.subscribeCrosshairMove((param) => {
    if (!param || !param.time) {
        currentHoverLogical = null;
        updateStatusBar(null);
        return;
    }
    if (typeof param.logical === "number") {
        currentHoverLogical = param.logical;
    }
    const key = createTimeKey(param.time);
    updateStatusBar(key);
});

setActiveIntervalButton(currentInterval);
updateVolumeButton();
updateCvdButtonState();
bootstrapDatasets();

observeChartContainer(priceContainer, priceChart);
observeChartContainer(obvContainer, obvChart);
observeChartContainer(rsiContainer, rsiChart);
observeChartContainer(timeAxisContainer, timeAxisChart);
[priceContainer, obvContainer, rsiContainer, timeAxisContainer].forEach(
    registerZoomContainer
);
zoomContainers.forEach((container) => {
    container.addEventListener("wheel", handleWheelZoom, { passive: false });
});
if (priceContainer) {
    priceContainer.addEventListener("dblclick", handlePriceAxisDoubleClick);
}

const resizeObserver = new ResizeObserver((entries) => {
    for (const entry of entries) {
        const chart = containerChartMap.get(entry.target);
        if (!chart) continue;
        const { width, height } = entry.contentRect;
        chart.applyOptions({ width, height });
    }
});
resizeObserverInstance = resizeObserver;
containerChartMap.forEach((_, container) =>
    resizeObserver.observe(container)
);
