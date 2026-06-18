import math
from typing import List, Tuple, Optional
from bot.structs import (
    OHLCV_Bar, SetupCandidate, SetupType, SetupClass, Direction
)
from bot.config import (
    RSI_DIV_EXTREME_LOW, RSI_DIV_EXTREME_HIGH, MIN_STOP_ATR_MULT,
    MOMENTUM_DIVERGENCE_MIN_STRENGTH
)
from bot.indicators import core


def _find_pivot_low(
    bars: List[OHLCV_Bar],
    rsis: List[float],
    n: int = 2,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (price_low, rsi_at_low) for the most recent local pivot low in bars,
    or (None, None) if no qualifying pivot exists.
    A pivot low at index i requires bars[i].low to be the minimum across the
    surrounding 2*n window.
    """
    for i in range(len(bars) - 1 - n, n - 1, -1):
        is_pivot = all(
            bars[i].low <= bars[i + k].low
            for k in range(-n, n + 1)
            if k != 0
        )
        if is_pivot and not math.isnan(rsis[i]):
            return bars[i].low, rsis[i]
    return None, None


def _find_pivot_high(
    bars: List[OHLCV_Bar],
    rsis: List[float],
    n: int = 2,
) -> Tuple[Optional[float], Optional[float]]:
    """
    Return (price_high, rsi_at_high) for the most recent local pivot high in bars,
    or (None, None) if no qualifying pivot exists.
    """
    for i in range(len(bars) - 1 - n, n - 1, -1):
        is_pivot = all(
            bars[i].high >= bars[i + k].high
            for k in range(-n, n + 1)
            if k != 0
        )
        if is_pivot and not math.isnan(rsis[i]):
            return bars[i].high, rsis[i]
    return None, None


def detect_momentum_divergence(
    bars: List[OHLCV_Bar],
    atr: float,
    lookback: int = 40,
) -> List[SetupCandidate]:
    """
    Detect RSI divergence on the current bar.

    Bullish: current bar makes a lower price low than the most recent pivot low,
             but RSI is higher (at least one RSI reading < RSI_DIV_EXTREME_LOW).
    Bearish: current bar makes a higher price high than the most recent pivot high,
             but RSI is lower (at least one RSI reading > RSI_DIV_EXTREME_HIGH).
    """
    candidates: List[SetupCandidate] = []

    if len(bars) < 15 or atr <= 0:
        return candidates

    closes = [b.close for b in bars]
    rsi_series: List[float] = core.rsi(closes, period=14)

    current_bar = bars[-1]
    current_rsi = rsi_series[-1]

    if math.isnan(current_rsi):
        return candidates

    start_idx = max(0, len(bars) - lookback - 1)
    window_bars = bars[start_idx:-1]
    window_rsis = rsi_series[start_idx:-1]

    if not window_bars:
        return candidates

    # ── Bullish Divergence ────────────────────────────────────────────────────
    prev_pivot_low, prev_pivot_rsi = _find_pivot_low(window_bars, window_rsis)

    if prev_pivot_low is not None and prev_pivot_rsi is not None:
        price_diverges = current_bar.low < prev_pivot_low
        rsi_diverges   = current_rsi > prev_pivot_rsi
        strength_ok    = (current_rsi - prev_pivot_rsi) >= MOMENTUM_DIVERGENCE_MIN_STRENGTH
        extreme_ok     = (
            current_rsi < RSI_DIV_EXTREME_LOW
            or prev_pivot_rsi < RSI_DIV_EXTREME_LOW
        )

        if price_diverges and rsi_diverges and strength_ok and extreme_ok:
            stop_price = current_bar.low - (MIN_STOP_ATR_MULT * atr)
            candidates.append(SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.MOMENTUM_DIVERGENCE,
                setup_class=SetupClass.REVERSAL,
                direction=Direction.UP,
                trigger_pivot=None,
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars) - 1,
                trigger_price=current_bar.close,
                stop_price=stop_price,
            ))

    # ── Bearish Divergence ────────────────────────────────────────────────────
    prev_pivot_high, prev_pivot_rsi_h = _find_pivot_high(window_bars, window_rsis)

    if prev_pivot_high is not None and prev_pivot_rsi_h is not None:
        price_diverges = current_bar.high > prev_pivot_high
        rsi_diverges   = current_rsi < prev_pivot_rsi_h
        strength_ok    = (prev_pivot_rsi_h - current_rsi) >= MOMENTUM_DIVERGENCE_MIN_STRENGTH
        extreme_ok     = (
            current_rsi > RSI_DIV_EXTREME_HIGH
            or prev_pivot_rsi_h > RSI_DIV_EXTREME_HIGH
        )

        if price_diverges and rsi_diverges and strength_ok and extreme_ok:
            stop_price = current_bar.high + (MIN_STOP_ATR_MULT * atr)
            candidates.append(SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.MOMENTUM_DIVERGENCE,
                setup_class=SetupClass.REVERSAL,
                direction=Direction.DOWN,
                trigger_pivot=None,
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars) - 1,
                trigger_price=current_bar.close,
                stop_price=stop_price,
            ))

    return candidates