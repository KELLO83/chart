import csv
import json
import logging
from datetime import datetime
from pathlib import Path
from typing import Dict, Any, Union, Optional

import pandas as pd

from mcp.server.fastmcp import FastMCP
from pykrx.stock.stock_api import get_market_ohlcv, get_nearest_business_day_in_a_week, get_market_cap, \
    get_market_fundamental_by_date, get_market_trading_volume_by_date, get_market_trading_volume_by_investor, \
    get_previous_business_days, get_index_ohlcv_by_date
from pykrx.website.krx.market.wrap import get_market_ticker_and_name
import ccxt
import yfinance as yf

try:
    from stock_update import StockDataUpdater
except Exception:  # pragma: no cover
    StockDataUpdater = None

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s'
)

# Create MCP server (add pykrx dependency)
mcp = FastMCP(
    "kospi-kosdaq-stock-server",
    dependencies=["pykrx", "ccxt", "yfinance"]
)

# Global variable to store ticker information in memory
TICKER_MAP: Dict[str, str] = {}

# Directory for exporting investor trading volume snapshots
TRADING_VOLUME_EXPORT_DIR = Path.cwd() / "trading_volume_exports"
TRADING_VOLUME_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Sub-directory for daily investor trading volume exports
INVESTOR_DAILY_EXPORT_DIR = TRADING_VOLUME_EXPORT_DIR / "daily_investor"
INVESTOR_DAILY_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Directory where the main FastAPI app loads OHLCV CSV datasets from
STOCK_DATA_EXPORT_DIR = (Path(__file__).resolve().parent.parent / "stock_data").resolve()
STOCK_DATA_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Directory for exporting crypto data
CRYPTO_DATA_EXPORT_DIR = (Path(__file__).resolve().parent.parent / "crypto_data").resolve()
CRYPTO_DATA_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

# Directory for exporting NASDAQ data
NASDAQ_DATA_EXPORT_DIR = (Path(__file__).resolve().parent.parent / "nasdaq_data").resolve()
NASDAQ_DATA_EXPORT_DIR.mkdir(parents=True, exist_ok=True)

@mcp.tool()
def load_all_tickers() -> Dict[str, str]:
    """Loads all ticker symbols and names for KOSPI and KOSDAQ into memory.

    Returns:
        Dict[str, str]: A dictionary mapping tickers to stock names.
        Example: {"005930": "삼성전자", "035720": "카카오", ...}
    """
    try:
        global TICKER_MAP

        # If TICKER_MAP already has data, return it
        if TICKER_MAP:
            logging.debug(f"Returning cached ticker information with {len(TICKER_MAP)} stocks")
            return TICKER_MAP

        logging.debug("No cached data found. Loading KOSPI/KOSDAQ ticker symbols")

        # Retrieve data based on today's date
        today = get_nearest_business_day_in_a_week()
        logging.debug(f"Reference date: {today}")

        # get_market_ticker_and_name() returns a Series,
        # where the index is the ticker and the values are the stock names
        kospi_series = get_market_ticker_and_name(today, market="KOSPI")
        kosdaq_series = get_market_ticker_and_name(today, market="KOSDAQ")

        # Convert Series to dictionaries and merge them
        TICKER_MAP.update(kospi_series.to_dict())
        TICKER_MAP.update(kosdaq_series.to_dict())

        logging.debug(f"Successfully stored information for {len(TICKER_MAP)} stocks")
        return TICKER_MAP

    except Exception as e:
        error_message = f"Failed to retrieve ticker information: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}

@mcp.resource("stock://tickers")
def get_ticker_map() -> str:
    """Retrieves the stored ticker symbol-name mapping information."""
    try:
        if not TICKER_MAP:
            return json.dumps({"message": "No ticker information stored. Please run the load_all_tickers() tool first to load ticker information."})

        # Return formatted for better readability
        # result = ["[Ticker Symbol - Stock Name Mapping]"]
        # for ticker, name in TICKER_MAP.items():
        #     result.append(f"- {ticker}: {name}")
        # return "\n".join(result)
        return json.dumps(TICKER_MAP)

    except Exception as e:
      return json.dumps({"error": f"Failed to retrieve ticker information: {str(e)}"})

@mcp.prompt()
def search_stock_data_prompt() -> str:
    """Prompt template for searching stock data."""
    return """
    Step-by-step guide for searching stock data by stock name:

    1. First, load the ticker information for all stocks:
       load_all_tickers()

    2. Check the code of the desired stock from the loaded ticker information:
       Refer to the stock://tickers resource to find the ticker corresponding to the stock name.

    3. Retrieve the desired data using the found ticker:

       Retrieve OHLCV (Open/High/Low/Close/Volume) data:
       get_stock_ohlcv("start_date", "end_date", "ticker", adjusted=True)

       Retrieve market capitalization data:
       get_stock_market_cap("start_date", "end_date", "ticker")

       Retrieve fundamental indicators (PER/PBR/Dividend Yield):
       get_stock_fundamental("start_date", "end_date", "ticker")

       Retrieve trading volume by investor type:
       get_stock_trading_volume("start_date", "end_date", "ticker")

       Retrieve index OHLCV data (KOSPI, KOSDAQ, etc.):
       get_index_ohlcv("start_date", "end_date", "ticker", freq="d")
       - ticker: 1001 for KOSPI, 2001 for KOSDAQ
       - freq: "d" for daily, "m" for monthly, "y" for yearly

    Example) To retrieve data for Samsung Electronics in January 2024:
    1. load_all_tickers()  # Load all tickers
    2. Refer to stock://tickers  # Check Samsung Electronics = 005930
    3. get_stock_ohlcv("20240101", "20240131", "005930")  # Retrieve OHLCV data
       or
       get_stock_market_cap("20240101", "20240131", "005930")  # Retrieve market cap data
       or
       get_stock_fundamental("20240101", "20240131", "005930")  # Retrieve fundamental data
       or
       get_stock_trading_volume("20240101", "20240131", "005930")  # Retrieve trading volume

    Example) To retrieve KOSPI index data for January 2021:
       get_index_ohlcv("20210101", "20210131", "1001", freq="d")  # Daily KOSPI data
    """

@mcp.tool()
def get_stock_ohlcv(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int], adjusted: bool = True) -> Dict[str, Any]:
    """Retrieves OHLCV (Open/High/Low/Close/Volume) data for a specific stock.

    Args:
        fromdate (str): Start date for retrieval (YYYYMMDD)
        todate   (str): End date for retrieval (YYYYMMDD)
        ticker   (str): Stock ticker symbol
        adjusted (bool, optional): Whether to use adjusted prices (True: adjusted, False: unadjusted). Defaults to True.

    Returns:
        DataFrame:
            >> get_stock_ohlcv("20210118", "20210126", "005930")
                            Open     High     Low    Close   Volume
            Date
            2021-01-26  89500  94800  89500  93800  46415214
            2021-01-25  87300  89400  86800  88700  25577517
            2021-01-22  89000  89700  86800  86800  30861661
            2021-01-21  87500  88600  86500  88100  25318011
            2021-01-20  89000  89000  86500  87200  25211127
            2021-01-19  84500  88000  83600  87000  39895044
            2021-01-18  86600  87300  84100  85000  43227951
    """
    # Validate and convert date format
    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            # Convert if in YYYY-MM-DD format
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            # Validate if in YYYYMMDD format
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(f"Retrieving stock OHLCV data: {ticker}, {fromdate}-{todate}, adjusted={adjusted}")

        # Call get_market_ohlcv (changed adj -> adjusted)
        df = get_market_ohlcv(fromdate, todate, ticker, adjusted=adjusted)

        # Convert DataFrame to dictionary
        result = df.to_dict(orient='index')

        # Convert datetime index to string and sort in reverse
        sorted_items = sorted(
            ((k.strftime('%Y-%m-%d'), v) for k, v in result.items()),
            reverse=True
        )
        result = dict(sorted_items)

        return result

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}

@mcp.resource("stock://format-guide")
def get_format_guide() -> str:
    """Provides a guide for date format and ticker symbol input."""
    return """
    [Input Format Guide]
    1. Ticker symbol: 6-digit number (e.g., 005930 - Samsung Electronics)
    2. Date format: YYYYMMDD (e.g., 20240301) or YYYY-MM-DD (e.g., 2024-03-01)

    [Notes]
    - The start date must be earlier than the end date.
    - If adjusted=True, adjusted prices are retrieved; if False, unadjusted prices are retrieved.
    """

@mcp.resource("stock://popular-tickers")
def get_popular_tickers() -> str:
    """Provides a list of frequently queried ticker symbols."""
    return """
    [Frequently Queried Ticker Symbols]
    - 005930: 삼성전자
    - 000660: SK하이닉스
    - 373220: LG에너지솔루션
    - 035420: NAVER
    - 035720: 카카오
    """

@mcp.prompt()
def get_stock_data_prompt() -> str:
    """Prompt template for retrieving stock data."""
    return """
    Please enter the following information to retrieve stock OHLCV data:

    1. Ticker symbol: 6-digit number (e.g., 005930)
    2. Start date: YYYYMMDD format (e.g., 20240101)
    3. End date: YYYYMMDD format (e.g., 20240301)
    4. Adjusted price: True/False (default: True)

    Example) get_stock_ohlcv("20240101", "20240301", "005930", adjusted=True)
    """


@mcp.tool()
def update_stock_data(dataset_id: Optional[str] = None) -> Dict[str, Any]:
    """Triggers stock_update.StockDataUpdater to append missing OHLCV rows."""
    if StockDataUpdater is None:
        return {
            "error": "StockDataUpdater 모듈을 불러올 수 없습니다. "
                     "stock_update.py가 경로에 있는지 확인하세요."
        }
    try:
        updater = StockDataUpdater()
    except Exception as exc:
        return {"error": f"StockDataUpdater 초기화 실패: {exc}"}

    def _append_count(dataset: str) -> int:
        frame = updater.update_dataset(dataset)
        return 0 if frame is None else len(frame)

    if dataset_id:
        if dataset_id not in updater.dataset_tickers:
            return {"error": f"알 수 없는 dataset_id: {dataset_id}"}
        count = _append_count(dataset_id)
        return {
            "dataset": dataset_id,
            "rows_appended": count,
            "status": "up_to_date" if count == 0 else "updated",
        }

    summary: Dict[str, int] = {}
    for dataset in sorted(updater.dataset_tickers):
        summary[dataset] = _append_count(dataset)

    total = sum(summary.values())
    return {
        "status": "updated" if total else "no_changes",
        "rows_appended": total,
        "details": summary,
    }

@mcp.tool()
def get_stock_market_cap(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int]) -> Dict[str, Any]:
    """Retrieves market capitalization data for a specific stock.

    Args:
        fromdate (str): Start date for retrieval (YYYYMMDD)
        todate   (str): End date for retrieval (YYYYMMDD)
        ticker   (str): Stock ticker symbol

    Returns:
        DataFrame:
            >> get_stock_market_cap("20150720", "20150724", "005930")
                              Market Cap  Volume      Trading Value  Listed Shares
            Date
            2015-07-24  181030885173000  196584  241383636000  147299337
            2015-07-23  181767381858000  208965  259446564000  147299337
            2015-07-22  184566069261000  268323  333813094000  147299337
            2015-07-21  186039062631000  194055  244129106000  147299337
            2015-07-20  187806654675000  128928  165366199000  147299337
    """
    # Validate and convert date format
    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            # Convert if in YYYY-MM-DD format
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            # Validate if in YYYYMMDD format
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(f"Retrieving stock market capitalization data: {ticker}, {fromdate}-{todate}")

        # Call get_market_cap
        df = get_market_cap(fromdate, todate, ticker)

        # Convert DataFrame to dictionary
        result = df.to_dict(orient='index')

        # Convert datetime index to string and sort in reverse
        sorted_items = sorted(
            ((k.strftime('%Y-%m-%d'), v) for k, v in result.items()),
            reverse=True
        )
        result = dict(sorted_items)

        return result

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}

@mcp.tool()
def get_stock_fundamental(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int]) -> Dict[str, Any]:
    """Retrieves fundamental data (PER/PBR/Dividend Yield) for a specific stock.

    Args:
        fromdate (str): Start date for retrieval (YYYYMMDD)
        todate   (str): End date for retrieval (YYYYMMDD)
        ticker   (str): Stock ticker symbol

    Returns:
        DataFrame:
            >> get_stock_fundamental("20210104", "20210108", "005930")
                              BPS        PER       PBR   EPS       DIV   DPS
                Date
                2021-01-08  37528  28.046875  2.369141  3166  1.589844  1416
                2021-01-07  37528  26.187500  2.210938  3166  1.709961  1416
                2021-01-06  37528  25.953125  2.189453  3166  1.719727  1416
                2021-01-05  37528  26.500000  2.240234  3166  1.690430  1416
                2021-01-04  37528  26.218750  2.210938  3166  1.709961  1416
    """
    # Validate and convert date format
    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(f"Retrieving stock fundamental data: {ticker}, {fromdate}-{todate}")

        # Call get_market_fundamental_by_date
        df = get_market_fundamental_by_date(fromdate, todate, ticker)

        # Convert DataFrame to dictionary
        result = df.to_dict(orient='index')

        # Convert datetime index to string and sort in reverse
        sorted_items = sorted(
            ((k.strftime('%Y-%m-%d'), v) for k, v in result.items()),
            reverse=True
        )
        result = dict(sorted_items)

        return result

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}

@mcp.tool()
def get_stock_trading_volume(
    fromdate: Union[str, int],
    todate: Union[str, int],
    ticker: Union[str, int],
    detail: bool = False,
) -> Dict[str, Any]:
    """Retrieves trading volume by investor type for a specific stock.

    Args:
        fromdate (str): Start date for retrieval (YYYYMMDD)
        todate   (str): End date for retrieval (YYYYMMDD)
        ticker   (str): Stock ticker symbol

    Returns:
        DataFrame with columns (기본: 개인/외국인/기관합계/기타법인/전체).
        detail=True 로 호출하면 금융투자, 보험, 투신, 사모, 은행, 연기금, 기타법인, 기타기관 등
        세부 투자자 그룹별 순매수 데이터를 포함합니다.
    """
    # Validate and convert date format
    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(
            "Retrieving stock trading volume by investor type: %s, %s-%s, detail=%s",
            ticker,
            fromdate,
            todate,
            detail,
        )

        # Call get_market_trading_volume_by_date with optional detail flag
        df = get_market_trading_volume_by_date(
            fromdate,
            todate,
            ticker,
            detail=detail,
        )

        # Persist investor flow data as CSV for downstream analysis
        suffix = "detail" if detail else "summary"
        csv_path = (
            TRADING_VOLUME_EXPORT_DIR
            / f"trading_volume_{ticker}_{fromdate}_{todate}_{suffix}.csv"
        )
        try:
            df.to_csv(csv_path, encoding='utf-8-sig')
            logging.info(f"Saved trading volume snapshot to CSV: {csv_path}")
        except Exception as save_error:
            logging.warning(f"Failed to save trading volume CSV ({csv_path}): {save_error}")

        # Convert DataFrame to dictionary
        result = df.to_dict(orient='index')

        # Convert datetime index to string and sort in reverse
        sorted_items = sorted(
            ((k.strftime('%Y-%m-%d'), v) for k, v in result.items()),
            reverse=True
        )
        result = dict(sorted_items)

        return result

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


@mcp.tool()
def get_investor_trading_volume(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int]) -> Dict[str, Any]:
    """Retrieves aggregate trading volume by investor type (sell/buy/net) for a stock.

    Mirrors pykrx's ``get_market_trading_volume_by_investor`` so tools can
    programmatically fetch tables such as 금융투자/보험/투신 등 투자자 그룹의 순매수 현황.
    """

    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(
            f"Retrieving investor trading volume: ticker={ticker}, range={fromdate}-{todate}"
        )

        df = get_market_trading_volume_by_investor(fromdate, todate, ticker)
        result = df.to_dict(orient='index')

        # Ensure index labels (investor categories) are strings for JSON output
        normalized = {str(index): values for index, values in result.items()}
        return normalized

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


@mcp.tool()
def export_stock_ohlcv_dataset(
    fromdate: Union[str, int],
    todate: Union[str, int],
    ticker: Union[str, int],
    dataset_name: Optional[str] = None,
    adjusted: bool = True,
) -> Dict[str, Any]:
    """Exports OHLCV 데이터셋을 ETHUSDT CSV 포맷(date/open/high/low/close/volume)으로 저장합니다.

    Args:
        fromdate, todate: 조회 구간 (YYYYMMDD or YYYY-MM-DD)
        ticker: 6자리 종목 코드
        dataset_name: 저장할 파일명(확장자 제외). 미입력 시 ``{ticker}_{from}_{to}_OHLCV`` 사용
        adjusted: 수정주가 사용 여부
    Returns:
        저장된 CSV 경로와 행 수 등의 메타데이터
    """

    def validate_date(date_value: Union[str, int]) -> str:
        try:
            if isinstance(date_value, int):
                date_value = str(date_value)
            if "-" in str(date_value):
                parsed = datetime.strptime(str(date_value), "%Y-%m-%d")
                return parsed.strftime("%Y%m%d")
            datetime.strptime(str(date_value), "%Y%m%d")
            return str(date_value)
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_value}")

    def normalize_ticker(value: Union[str, int]) -> str:
        return str(value).strip()

    def resolve_dataset_name(default_ticker: str, start: str, end: str, custom: Optional[str]) -> str:
        if custom:
            return custom.strip().replace(" ", "_")
        return f"{default_ticker}_{start}_{end}_OHLCV"

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = normalize_ticker(ticker)

        logging.debug(
            "Exporting OHLCV dataset: ticker=%s, range=%s-%s, adjusted=%s",
            ticker,
            fromdate,
            todate,
            adjusted,
        )

        df = get_market_ohlcv(fromdate, todate, ticker, adjusted=adjusted)
        if df.empty:
            raise ValueError("No OHLCV data returned for the requested range.")

        column_aliases = {
            "시가": "open",
            "고가": "high",
            "저가": "low",
            "종가": "close",
            "거래량": "volume",
            "open": "open",
            "high": "high",
            "low": "low",
            "close": "close",
            "volume": "volume",
        }

        normalized_df = pd.DataFrame(index=df.index)
        for column in df.columns:
            raw = str(column).strip()
            alias = column_aliases.get(raw) or column_aliases.get(raw.lower())
            if alias in {"open", "high", "low", "close", "volume"}:
                normalized_df[alias] = pd.to_numeric(df[column], errors="coerce")

        required_cols = ["open", "high", "low", "close", "volume"]
        missing_cols = [col for col in required_cols if col not in normalized_df.columns]
        if missing_cols:
            raise ValueError(f"Missing required OHLCV columns: {', '.join(missing_cols)}")

        normalized_df = normalized_df.dropna(subset=["open", "high", "low", "close"])
        normalized_df["volume"] = normalized_df["volume"].fillna(0)
        if normalized_df.empty:
            raise ValueError("No usable OHLCV rows after cleaning.")

        normalized_df.insert(0, "date", normalized_df.index.strftime("%Y-%m-%d 09:00:00"))
        normalized_df = normalized_df[["date", "open", "high", "low", "close", "volume"]]

        dataset_id = resolve_dataset_name(ticker, fromdate, todate, dataset_name)
        csv_path = STOCK_DATA_EXPORT_DIR / f"{dataset_id}.csv"
        normalized_df.to_csv(csv_path, index=False)

        logging.info("Saved OHLCV dataset to %s (%d rows)", csv_path, len(normalized_df))

        return {
            "file": str(csv_path),
            "dataset_id": dataset_id,
            "rows": len(normalized_df),
            "start": normalized_df["date"].iloc[0],
            "end": normalized_df["date"].iloc[-1],
        }

    except Exception as e:
        error_message = f"Failed to export OHLCV dataset: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


@mcp.tool()
def export_daily_investor_trading_volume(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int]) -> Dict[str, Any]:
    """Exports day-by-day investor trading volume (sell/buy/net) to a CSV file.

    Returns metadata about the written CSV so downstream tools can load it.
    """

    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)

        logging.debug(
            f"Exporting daily investor trading volume: ticker={ticker}, range={fromdate}-{todate}"
        )

        business_days = get_previous_business_days(fromdate=fromdate, todate=todate)
        if not business_days:
            raise ValueError("No business days found for the provided date range.")

        csv_path = INVESTOR_DAILY_EXPORT_DIR / f"investor_daily_{ticker}_{fromdate}_{todate}.csv"
        total_rows = 0
        fieldnames = ["date", "investor", "sell", "buy", "net"]
        with csv_path.open("w", newline="", encoding="utf-8-sig") as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=fieldnames)
            writer.writeheader()
            for ts in business_days:
                day_str = ts.strftime("%Y%m%d")
                display_day = ts.strftime("%Y-%m-%d")
                df = get_market_trading_volume_by_investor(day_str, day_str, ticker)
                if df.empty:
                    continue
                day_table = df.reset_index()
                investor_col = day_table.columns[0]
                for _, row in day_table.iterrows():
                    try:
                        writer.writerow({
                            "date": display_day,
                            "investor": str(row[investor_col]),
                            "sell": int(row.get("매도", 0)),
                            "buy": int(row.get("매수", 0)),
                            "net": int(row.get("순매수", 0)),
                        })
                        total_rows += 1
                    except Exception as write_error:
                        logging.warning(
                            f"Skipping row for {display_day}/{row[investor_col]} due to error: {write_error}"
                        )

        logging.info(
            f"Saved daily investor trading volume CSV ({total_rows} rows) to {csv_path}"
        )

        return {
            "file": str(csv_path),
            "business_days": len(business_days),
            "rows": total_rows,
        }

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


@mcp.tool()
def get_index_ohlcv(fromdate: Union[str, int], todate: Union[str, int], ticker: Union[str, int], freq: str = 'd') -> \
Dict[str, Any]:
    """Retrieves OHLCV data for a specific index.

    Args:
        fromdate (str): Start date for retrieval (YYYYMMDD)
        todate   (str): End date for retrieval (YYYYMMDD)
        ticker   (str): Index ticker symbol (e.g., 1001 for KOSPI, 2001 for KOSDAQ)
        freq     (str, optional): d - daily / m - monthly / y - yearly. Defaults to 'd'.

    Returns:
        DataFrame:
            >> get_index_ohlcv("20210101", "20210130", "1001")
                           Open     High      Low    Close       Volume    Trading Value
            Date
            2021-01-04  2874.50  2946.54  2869.11  2944.45  1026510465  25011393960858
            2021-01-05  2943.67  2990.57  2921.84  2990.57  1519911750  26548380179493
            2021-01-06  2993.34  3027.16  2961.37  2968.21  1793418534  29909396443430
            2021-01-07  2980.75  3055.28  2980.75  3031.68  1524654500  27182807334912
            2021-01-08  3040.11  3161.11  3040.11  3152.18  1297903388  40909490005818
    """

    # Validate and convert date format
    def validate_date(date_str: Union[str, int]) -> str:
        try:
            if isinstance(date_str, int):
                date_str = str(date_str)
            if '-' in date_str:
                parsed_date = datetime.strptime(date_str, '%Y-%m-%d')
                return parsed_date.strftime('%Y%m%d')
            datetime.strptime(date_str, '%Y%m%d')
            return date_str
        except ValueError:
            raise ValueError(f"Date must be in YYYYMMDD format. Input value: {date_str}")

    def validate_ticker(ticker_str: Union[str, int]) -> str:
        if isinstance(ticker_str, int):
            return str(ticker_str)
        return ticker_str

    def validate_freq(freq_str: str) -> str:
        valid_freqs = ['d', 'm', 'y']
        if freq_str not in valid_freqs:
            raise ValueError(f"Frequency must be one of {valid_freqs}. Input value: {freq_str}")
        return freq_str

    try:
        fromdate = validate_date(fromdate)
        todate = validate_date(todate)
        ticker = validate_ticker(ticker)
        freq = validate_freq(freq)

        logging.debug(f"Retrieving index OHLCV data: {ticker}, {fromdate}-{todate}, freq={freq}")

        # Call get_index_ohlcv_by_date
        # Note: name_display is set to False to match the pattern of other functions
        df = get_index_ohlcv_by_date(fromdate, todate, ticker, freq=freq, name_display=False)

        # Convert DataFrame to dictionary
        result = df.to_dict(orient='index')

        # Convert datetime index to string and sort in reverse
        sorted_items = sorted(
            ((k.strftime('%Y-%m-%d'), v) for k, v in result.items()),
            reverse=True
        )
        result = dict(sorted_items)

        return result

    except Exception as e:
        error_message = f"Data retrieval failed: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}


def main():
    mcp.run()


if __name__ == "__main__":
    main()
    
@mcp.tool()
def fetch_bybit_candles(symbol: str, timeframe: str = '1d', limit: int = 200) -> Dict[str, Any]:
    """Fetches OHLCV data from Bybit and saves it as a CSV file.

    Args:
        symbol (str): Trading pair symbol (e.g., 'BTC/USDT', 'ETH/USDT').
        timeframe (str, optional): Candle timeframe ('1d', '1h', '15m', etc.). Defaults to '1d'.
        limit (int, optional): Number of candles to fetch. Defaults to 200.

    Returns:
        Dict[str, Any]: Metadata about the saved dataset.
    """
    try:
        logging.debug(f"Fetching Bybit candles: {symbol}, {timeframe}, limit={limit}")
        
        exchange = ccxt.bybit()
        ohlcv = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
        
        if not ohlcv:
            raise ValueError(f"No data returned from Bybit for {symbol}")

        # Convert to DataFrame
        # ccxt structure: [timestamp, open, high, low, close, volume]
        df = pd.DataFrame(ohlcv, columns=['timestamp', 'open', 'high', 'low', 'close', 'volume'])
        
        # Convert timestamp (ms) to datetime string
        df['date'] = pd.to_datetime(df['timestamp'], unit='ms')
        
        # Format date column. For '1d', we might want YYYY-MM-DD. For others, full timestamp.
        # To be safe and consistent with main.py's parser, we'll use a full ISO-like string.
        df['date'] = df['date'].dt.strftime('%Y-%m-%d %H:%M:%S')
        
        # Reorder columns to match expected format: date, open, high, low, close, volume
        df = df[['date', 'open', 'high', 'low', 'close', 'volume']]
        
        # Generate filename
        safe_symbol = symbol.replace('/', '')
        dataset_id = f"{safe_symbol}_{timeframe}_OHLCV"
        csv_path = CRYPTO_DATA_EXPORT_DIR / f"{dataset_id}.csv"
        
        # Save to CSV
        df.to_csv(csv_path, index=False)
        logging.info(f"Saved Bybit dataset to {csv_path} ({len(df)} rows)")
        
        return {
            "file": str(csv_path),
            "dataset_id": dataset_id,
            "rows": len(df),
            "start": df['date'].iloc[0],
            "end": df['date'].iloc[-1],
            "symbol": symbol,
            "timeframe": timeframe
        }

    except Exception as e:
        error_message = f"Failed to fetch Bybit data: {str(e)}"
        logging.error(error_message)
        return {"error": error_message}
