"""Ichimoku Cloud helper utilities.

현재 프로젝트에서는 일목균형표(일명 일목운)를 전체 구성요소 대신
"선행스팬 A"와 "선행스팬 B" 두 가닥만 사용한다. 두 스팬이 만들어 내는
구름의 색상은 트레이딩뷰 다크 테마 기준으로 양운(Span A > Span B)은
녹색, 음운은 빨간색을 사용한다.
"""

from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

__all__ = [
    "CLOUD_BULLISH_COLOR",
    "CLOUD_BEARISH_COLOR",
    "IchimokuCloud",
    "compute_ichimoku_cloud",
]


CLOUD_BULLISH_COLOR = "#089981"
CLOUD_BEARISH_COLOR = "#f23645"


@dataclass(frozen=True)
class IchimokuCloud:
    """Container holding derived Ichimoku cloud values."""

    span_a: pd.Series
    span_b: pd.Series
    top: pd.Series
    bottom: pd.Series
    color: pd.Series


def _rolling_midpoint(high: pd.Series, low: pd.Series, window: int) -> pd.Series:
    highest = high.rolling(window).max()
    lowest = low.rolling(window).min()
    return (highest + lowest) / 2


def compute_ichimoku_cloud(
    high: pd.Series,
    low: pd.Series,
    conversion_period: int = 9,
    base_period: int = 26,
    span_b_period: int = 52,
    displacement: int = 26,
) -> IchimokuCloud:
    """Compute leading spans A/B (Senkou) for Ichimoku cloud.

    Args:
        high: 고가 시계열.
        low: 저가 시계열.
        conversion_period: 전환선 기간(Tenkan-sen).
        base_period: 기준선 기간(Kijun-sen).
        span_b_period: 선행스팬B 계산 기간.
        displacement: 선행 이동 길이(기본 26).

    Returns:
        IchimokuCloud dataclass with Senkou spans and precomputed
        cloud color (녹/적) for 빠른 프런트엔드 전송.
    """

    if high.empty or low.empty:
        empty = pd.Series(dtype="float64")
        color = pd.Series(dtype="object")
        return IchimokuCloud(empty, empty, empty, empty, color)

    joint = pd.concat({"high": high, "low": low}, axis=1).dropna()
    if joint.empty:
        empty = pd.Series(dtype="float64")
        color = pd.Series(dtype="object")
        return IchimokuCloud(empty, empty, empty, empty, color)

    conversion_line = _rolling_midpoint(joint["high"], joint["low"], conversion_period)
    base_line = _rolling_midpoint(joint["high"], joint["low"], base_period)

    span_a = ((conversion_line + base_line) / 2).shift(displacement)

    span_b = _rolling_midpoint(joint["high"], joint["low"], span_b_period)
    span_b = span_b.shift(displacement)

    top = span_a.combine(span_b, max)
    bottom = span_a.combine(span_b, min)
    color = pd.Series(CLOUD_BEARISH_COLOR, index=span_a.index)
    color = color.where(span_a < span_b, CLOUD_BULLISH_COLOR)

    valid = ~(span_a.isna() | span_b.isna())
    span_a = span_a[valid]
    span_b = span_b[valid]
    top = top[valid]
    bottom = bottom[valid]
    color = color[valid]

    return IchimokuCloud(span_a, span_b, top, bottom, color)
