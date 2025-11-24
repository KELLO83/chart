"""투자자별 일별 순매수/순매도량 조회 예제."""

from pykrx import stock


def get_daily_investor_volume_flows(ticker: str, start: str, end: str):
    """하루 단위로 투자자별 매수/매도/순매수량을 반환한다."""

    def _rename_columns(df, suffix):
        return df.rename(columns={col: f"{col}_{suffix}" for col in df.columns})

    buys = stock.get_market_trading_volume_by_date(start, end, ticker, on="매수")
    sells = stock.get_market_trading_volume_by_date(start, end, ticker, on="매도")
    net = buys - sells  # 양수=순매수, 음수=순매도

    combined = [_rename_columns(buys, "매수"),
                _rename_columns(sells, "매도"),
                _rename_columns(net, "순매수")]

    result = combined[0]
    for extra in combined[1:]:
        result = result.join(extra)
    return result


if __name__ == "__main__":
    ticker = "006400"
    start = "20241120"
    end = "20241121"

    df = get_daily_investor_volume_flows(ticker, start, end)
    print(df.tail())
