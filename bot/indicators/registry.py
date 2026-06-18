"""
registry.py — Stateful IndicatorState registry
================================================

Wraps the pure functions in core.py with a stateful registry keyed by
(asset, timeframe).  On each bar close:
  1. Append the new bar's close/high/low/open to rolling buffers.
  2. Re-compute indicators over the buffer.
  3. Write the latest value into IndicatorState.
  4. Push ema_50 onto ema_50_buffer (Resolution III-6).

The registry is the *only* place that calls core.py functions; all other
modules read from ``Indicators[asset][timeframe]`` directly.

Spec references
---------------
- Doc-3 §1  : Indicators registry data model
- III-6     : ema_50_buffer deque(maxlen=15) updated on each D1 close
- I-2       : ema_50_at_lag(n) consumes the buffer
"""

from __future__ import annotations

from collections import deque
from typing import Dict, List, Optional, Sequence

from bot.structs import OHLCV_Bar, IndicatorState
from bot.indicators import core

# ---------------------------------------------------------------------------
# Global registry
# ---------------------------------------------------------------------------
Indicators: Dict[str, Dict[str, IndicatorState]] = {}

# Rolling OHLCV buffers per (asset, timeframe) — newest value appended last.
# These feed the indicator computations.
_MAXLEN = 300  # enough history for ADX warm-up (2×14 + buffer)

_buffers: Dict[str, Dict[str, Dict[str, List[float]]]] = {}


def _ensure(asset: str, timeframe: str) -> None:
    """Initialise registry and buffer slots if they do not yet exist."""
    if asset not in Indicators:
        Indicators[asset] = {}
        _buffers[asset] = {}
    if timeframe not in Indicators[asset]:
        Indicators[asset][timeframe] = IndicatorState(asset=asset, timeframe=timeframe)
        _buffers[asset][timeframe] = {
            "open":  [],
            "high":  [],
            "low":   [],
            "close": [],
        }


def get_or_create(asset: str, timeframe: str) -> IndicatorState:
    """Return existing IndicatorState or create a blank one."""
    _ensure(asset, timeframe)
    return Indicators[asset][timeframe]


# ---------------------------------------------------------------------------
# Bar ingestion
# ---------------------------------------------------------------------------

def on_bar_close(bar: OHLCV_Bar) -> None:
    """
    Ingest one closed bar, update all indicators for (asset, timeframe).

    Called by the data-ingestion layer after each confirmed bar close.
    """
    asset, tf = bar.asset, bar.timeframe
    _ensure(asset, tf)

    buf = _buffers[asset][tf]
    buf["open"].append(bar.open)
    buf["high"].append(bar.high)
    buf["low"].append(bar.low)
    buf["close"].append(bar.close)

    # Trim to rolling window
    for key in buf:
        if len(buf[key]) > _MAXLEN:
            buf[key] = buf[key][-_MAXLEN:]

    _recompute(asset, tf, bar)


def _recompute(asset: str, tf: str, bar: OHLCV_Bar) -> None:
    """Recompute all indicators from current buffer and update IndicatorState."""
    buf = _buffers[asset][tf]
    opens  = buf["open"]
    highs  = buf["high"]
    lows   = buf["low"]
    closes = buf["close"]
    n = len(closes)

    state = Indicators[asset][tf]
    state.last_bar_timestamp = bar.timestamp

    # ATR(14)
    if n >= 2:
        atr_series = core.atr(highs, lows, closes, period=14)
        val = atr_series[-1]
        if not _isnan(val):
            state.atr_14 = val

    # EMA(50)
    if n >= 50:
        ema50_series = core.ema(closes, period=50)
        val = ema50_series[-1]
        if not _isnan(val):
            state.ema_50 = val
            state.ema_50_buffer.append(val)   # III-6: rolling 15-bar history

    # ADX(14)
    if n >= 29:  # 2*14 + 1 minimum
        adx_result = core.adx(highs, lows, closes, period=14)
        val = adx_result["adx"][-1]
        if not _isnan(val):
            state.adx = val

    # RSI(14)
    if n >= 15:
        rsi_series = core.rsi(closes, period=14)
        val = rsi_series[-1]
        if not _isnan(val):
            state.rsi_14 = val

    # Efficiency Ratio (period from CONFIG default = 10)
    if n > 10:
        er_series = core.efficiency_ratio(closes, period=10)
        val = er_series[-1]
        if not _isnan(val):
            state.efficiency_ratio = val


def _isnan(x: float) -> bool:
    import math
    return math.isnan(x)


# ---------------------------------------------------------------------------
# Lag accessor  (Resolution III-6)
# ---------------------------------------------------------------------------

def ema_50_at_lag(asset: str, timeframe: str, lag: int) -> Optional[float]:
    """
    Return the EMA-50 value ``lag`` bars ago.

    Uses the ema_50_buffer deque (maxlen=15) stored on IndicatorState.
    Resolution III-6: option (a) — rolling buffer, cheaper than re-scanning OHLCV.

    Returns None if the buffer does not yet have ``lag+1`` values.

    Example:
        ema_50_at_lag("BTC", "D1", 10)  →  EMA-50 from 10 bars ago
        Used by update_htf_bias for the EMA slope veto (Resolution I-2,
        EMA50_SLOPE_LAG_BARS = 10).
    """
    _ensure(asset, timeframe)
    buf: deque = Indicators[asset][timeframe].ema_50_buffer
    # buf[-1] is current, buf[-(lag+1)] is lag bars ago
    if len(buf) < lag + 1:
        return None
    return buf[-(lag + 1)]


# ---------------------------------------------------------------------------
# Bulk initialisation helper (for backtesting / warm-up)
# ---------------------------------------------------------------------------

def warm_up(asset: str, timeframe: str, bars: Sequence[OHLCV_Bar]) -> None:
    """
    Feed a historical bar series to warm up the indicator registry without
    triggering live side-effects.  Call once before the live loop starts.

    After this call, ``Indicators[asset][timeframe]`` contains valid indicator
    values assuming ``bars`` contains at least 50 candles (EMA-50 warm-up).
    """
    for bar in bars:
        on_bar_close(bar)
