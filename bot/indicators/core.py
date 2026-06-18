"""
core.py — Pure-function indicator computations
================================================

All functions are stateless: they take sequences and return lists of floats.
NaN sentinels (float('nan')) fill positions where the indicator is not yet
defined (warm-up period).

Smoothing convention
--------------------
ATR, RSI, and ADX all use **Wilder's RMA** (Running Moving Average):
    RMA[i] = (RMA[i-1] * (period - 1) + value[i]) / period
Seed value is the simple average of the first ``period`` inputs.
This matches TradingView Pine Script's ``ta.rma()`` exactly.

EMA uses the standard multiplier k = 2 / (period + 1), seeded with the
simple average of the first ``period`` closes — identical to TradingView's
``ta.ema()``.

Spec references
---------------
- III-6 : ema_50_buffer updated via ema() each D1 close
- I-2   : EMA-50 with EMA50_SLOPE_LAG_BARS=10 lag lookup
- §1.2  : ADX / ER used for trend classification
"""

from __future__ import annotations

import math
from typing import Sequence

_nan = float("nan")


# ============================================================================
# Internal helpers
# ============================================================================

def _is_valid(x: float) -> bool:
    return not math.isnan(x)


def _sma(values: Sequence[float], start: int, length: int) -> float:
    """Simple average of values[start : start+length]. All must be finite."""
    return sum(values[start : start + length]) / length


# ============================================================================
# Wilder's RMA  (used by ATR, RSI, ADX)
# ============================================================================

def wilder_rma(values: Sequence[float], period: int) -> list[float]:
    """
    Wilder's Running Moving Average over a pre-computed series.

    Seed: SMA of the first ``period`` *finite* values.
    Returns a list of the same length; leading positions are NaN.
    Matches TradingView ta.rma().
    """
    n = len(values)
    result = [_nan] * n
    if n < period:
        return result

    # Find first run of `period` consecutive finite values
    start = 0
    while start + period <= n:
        if all(_is_valid(values[i]) for i in range(start, start + period)):
            break
        start += 1
    else:
        return result

    result[start + period - 1] = _sma(values, start, period)
    for i in range(start + period, n):
        result[i] = (result[i - 1] * (period - 1) + values[i]) / period
    return result


# ============================================================================
# EMA
# ============================================================================

def ema(values: Sequence[float], period: int) -> list[float]:
    """
    Exponential Moving Average.  k = 2 / (period + 1).
    Seed: SMA of the first ``period`` closes.
    Matches TradingView ta.ema().

    Spec reference: III-6 (ema_50_buffer populated from this function each D1 bar).
    """
    n = len(values)
    result = [_nan] * n
    if n < period:
        return result

    k = 2.0 / (period + 1)
    result[period - 1] = _sma(values, 0, period)
    for i in range(period, n):
        result[i] = values[i] * k + result[i - 1] * (1.0 - k)
    return result


# ============================================================================
# ATR — Average True Range
# ============================================================================

def true_range(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """
    True Range for each bar.

    TR[0] = high[0] - low[0]  (no previous close available)
    TR[i] = max(high[i]-low[i], |high[i]-close[i-1]|, |low[i]-close[i-1]|)
    """
    n = len(highs)
    tr = [_nan] * n
    if n == 0:
        return tr
    tr[0] = highs[0] - lows[0]
    for i in range(1, n):
        hl = highs[i] - lows[i]
        hc = abs(highs[i] - closes[i - 1])
        lc = abs(lows[i] - closes[i - 1])
        tr[i] = max(hl, hc, lc)
    return tr


def atr(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> list[float]:
    """
    Average True Range using Wilder's RMA.
    Matches TradingView ta.atr(period).
    """
    tr = true_range(highs, lows, closes)
    return wilder_rma(tr, period)


# ============================================================================
# RSI — Relative Strength Index
# ============================================================================

def rsi(closes: Sequence[float], period: int = 14) -> list[float]:
    """
    RSI using Wilder's smoothing (RMA on gains and losses separately).
    Matches TradingView ta.rsi(source, period).

    First valid RSI is at index ``period`` (requires period+1 closes).
    """
    n = len(closes)
    result = [_nan] * n
    if n < period + 1:
        return result

    changes = [closes[i] - closes[i - 1] for i in range(1, n)]
    gains   = [max(c, 0.0) for c in changes]
    losses  = [max(-c, 0.0) for c in changes]

    # Seed: SMA of first `period` gains/losses
    avg_gain = sum(gains[:period]) / period
    avg_loss = sum(losses[:period]) / period

    def _rsi_from(ag: float, al: float) -> float:
        if al == 0.0:
            return 100.0
        return 100.0 - 100.0 / (1.0 + ag / al)

    result[period] = _rsi_from(avg_gain, avg_loss)

    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i - 1]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i - 1]) / period
        result[i] = _rsi_from(avg_gain, avg_loss)

    return result


# ============================================================================
# ADX — Average Directional Index
# ============================================================================

def adx(
    highs: Sequence[float],
    lows: Sequence[float],
    closes: Sequence[float],
    period: int = 14,
) -> dict[str, list[float]]:
    """
    Average Directional Index and directional indicators.

    Returns a dict with keys:
        'adx'    : ADX series
        'plus_di': +DI series
        'minus_di': -DI series

    Algorithm
    ---------
    For each bar i >= 1:
      up_move   = high[i] - high[i-1]
      down_move = low[i-1] - low[i]
      +DM = up_move   if up_move > down_move and up_move > 0 else 0
      -DM = down_move if down_move > up_move  and down_move > 0 else 0

    Smooth TR, +DM, -DM with Wilder's RMA(period).
    +DI = 100 * smoothed_+DM / smoothed_TR
    -DI = 100 * smoothed_-DM / smoothed_TR
    DX  = 100 * |+DI - -DI| / (+DI + -DI)
    ADX = Wilder's RMA(DX, period)

    Matches TradingView ta.adx(period).
    """
    n = len(highs)
    _z = [_nan] * n

    if n < 2 * period + 1:
        return {"adx": _z[:], "plus_di": _z[:], "minus_di": _z[:]}

    # Raw DM values (index 0 is undefined → NaN)
    plus_dm  = [_nan] + [0.0] * (n - 1)
    minus_dm = [_nan] + [0.0] * (n - 1)
    tr_raw   = true_range(highs, lows, closes)

    for i in range(1, n):
        up   = highs[i] - highs[i - 1]
        down = lows[i - 1] - lows[i]
        if up > down and up > 0:
            plus_dm[i] = up
        if down > up and down > 0:
            minus_dm[i] = down

    # Wilder's RMA — skip index 0 (NaN) by passing from index 1
    smooth_tr   = wilder_rma(tr_raw[1:],   period)
    smooth_pdm  = wilder_rma(plus_dm[1:],  period)
    smooth_mdm  = wilder_rma(minus_dm[1:], period)

    plus_di_s  = [_nan] * len(smooth_tr)
    minus_di_s = [_nan] * len(smooth_tr)
    dx_s       = [_nan] * len(smooth_tr)

    for i in range(len(smooth_tr)):
        sptr = smooth_tr[i]
        if _is_valid(sptr) and sptr != 0.0:
            pdi = 100.0 * smooth_pdm[i] / sptr
            mdi = 100.0 * smooth_mdm[i] / sptr
            plus_di_s[i]  = pdi
            minus_di_s[i] = mdi
            denom = pdi + mdi
            if denom != 0.0:
                dx_s[i] = 100.0 * abs(pdi - mdi) / denom

    adx_s = wilder_rma(dx_s, period)

    # Re-pad to length n (we dropped index 0)
    pad = [_nan]
    return {
        "adx":      pad + adx_s,
        "plus_di":  pad + plus_di_s,
        "minus_di": pad + minus_di_s,
    }


# ============================================================================
# Efficiency Ratio (Kaufman)
# ============================================================================

def efficiency_ratio(closes: Sequence[float], period: int = 10) -> list[float]:
    """
    Kaufman Efficiency Ratio.

    ER[i] = |close[i] - close[i-period]| / sum(|close[j]-close[j-1]|, j=i-period+1..i)

    Range 0 (choppy) to 1 (perfectly trending).
    Spec reference: §1.2 (TREND_CONFIRM_BARS=10 is the default period).
    CONFIG["ER_TREND_THRESHOLD"] = 0.6.
    """
    n = len(closes)
    result = [_nan] * n
    for i in range(period, n):
        direction  = abs(closes[i] - closes[i - period])
        volatility = sum(abs(closes[j] - closes[j - 1]) for j in range(i - period + 1, i + 1))
        result[i]  = direction / volatility if volatility != 0.0 else 0.0
    return result


# ============================================================================
# Candle wick / body ratio helpers
# ============================================================================

def body_size(opens: Sequence[float], closes: Sequence[float]) -> list[float]:
    """Absolute candle body height = |close - open|."""
    return [abs(c - o) for o, c in zip(opens, closes)]


def upper_wick(
    highs: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """Upper shadow = high - max(open, close)."""
    return [h - max(o, c) for h, o, c in zip(highs, opens, closes)]


def lower_wick(
    lows: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """Lower shadow = min(open, close) - low."""
    return [min(o, c) - l for l, o, c in zip(lows, opens, closes)]


def body_range_ratio(
    highs: Sequence[float],
    lows: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
) -> list[float]:
    """
    |close - open| / (high - low).  Zero when high == low (doji-flat bar).

    Used by Open Drive detection (DRIVE_BODY_RANGE_RATIO_MIN = 0.6)
    and Clean Break wick filter (BREAK_WICK_RATIO_MAX = 0.25).
    """
    result = []
    for h, l, o, c in zip(highs, lows, opens, closes):
        rng = h - l
        result.append(abs(c - o) / rng if rng != 0.0 else 0.0)
    return result


def wick_ratio(
    highs: Sequence[float],
    lows: Sequence[float],
    opens: Sequence[float],
    closes: Sequence[float],
    side: str = "rejection",
) -> list[float]:
    """
    Rejection-wick ratio used by is_clean_break (BREAK_WICK_RATIO_MAX = 0.25).

    side='rejection':
      For an UP break: upper_wick / total_range  (wick above body indicates rejection)
      For a DOWN break: lower_wick / total_range

    This function returns the *larger* of upper/lower wick ratios, which is
    the conservative (spec-safe) choice for the clean-break wick filter.
    Total range = high - low.  Zero on flat bars.
    """
    result = []
    for h, l, o, c in zip(highs, lows, opens, closes):
        rng = h - l
        if rng == 0.0:
            result.append(0.0)
            continue
        uw = (h - max(o, c)) / rng
        lw = (min(o, c) - l) / rng
        result.append(max(uw, lw))
    return result
