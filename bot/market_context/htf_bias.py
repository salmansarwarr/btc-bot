"""
htf_bias.py — Higher-timeframe directional bias logic
======================================================

**Spec reference:** Doc-1 §1.3; Doc-3 update_htf_bias pseudocode.
Resolution I-1: detect_factual_msb must accept lookback_bars (default N_HTF_BIAS_LOOKBACK=20).
Resolution I-2: EMA50_SLOPE_LAG_BARS=10 used for veto.
"""
from __future__ import annotations
from typing import Dict, Optional

from bot.structs import BiasState, PivotFlag, PivotStrength, Direction
from bot.config import N_HTF_BIAS_LOOKBACK, EMA50_SLOPE_LAG_BARS
from bot.market_context.pivot_registry import pivot_registry
from bot.indicators.registry import get_or_create as get_indicator_state, ema_50_at_lag
from bot.data_ingestion.ohlcv_buffer import get_bars

htf_bias: Dict[str, BiasState] = {}


def detect_factual_msb(
    asset: str,
    timeframe: str,
    lookback_bars: int = N_HTF_BIAS_LOOKBACK,
) -> Optional[PivotFlag]:
    """
    Search the pivot registry for the most-recent factual MSB within
    lookback_bars. Returns None (→ NEUTRAL bias) if none found.
    Resolution I-1: lookback_bars enforces the N=20 window from Doc-1 §1.3.
    """
    if asset not in pivot_registry or timeframe not in pivot_registry[asset]:
        return None
        
    pivots = pivot_registry[asset][timeframe]
    bars = get_bars(asset, timeframe, lookback_bars)
    if not bars:
        return None
        
    oldest_ts_in_window = bars[0].timestamp
    
    # We are looking for an MSB. An MSB occurs when price closes beyond a major pivot.
    # To find the most recent MSB, we check the bars in the lookback window.
    # For each bar, does it close above a recent major swing high? Or below a major swing low?
    
    recent_msb_pivot = None
    most_recent_msb_ts = None
    
    # Pre-filter major pivots
    major_pivots = [p for p in pivots if p.strength == PivotStrength.MAJOR]
    
    for bar in bars:
        for pivot in major_pivots:
            # Only consider pivots formed before this bar
            if pivot.timestamp >= bar.timestamp:
                continue
                
            is_msb = False
            if pivot.direction == Direction.UP and bar.close > pivot.price:
                is_msb = True
            elif pivot.direction == Direction.DOWN and bar.close < pivot.price:
                is_msb = True
                
            if is_msb:
                if most_recent_msb_ts is None or bar.timestamp > most_recent_msb_ts:
                    most_recent_msb_ts = bar.timestamp
                    recent_msb_pivot = pivot
                    
    return recent_msb_pivot


def update_htf_bias(asset: str) -> None:
    """
    Called on each D1 bar close.
    1. detect_factual_msb(asset, "D1")
    2. If last_msb found: apply EMA50 slope veto using ema_50_at_lag(EMA50_SLOPE_LAG_BARS)
    3. Set htf_bias[asset] = BULLISH | BEARISH | NEUTRAL
    """
    timeframe = "D1"
    msb_pivot = detect_factual_msb(asset, timeframe, lookback_bars=N_HTF_BIAS_LOOKBACK)
    
    if not msb_pivot:
        htf_bias[asset] = BiasState.NEUTRAL
        return
        
    # MSB direction:
    # If it broke a swing HIGH (Direction.UP), the MSB is BULLISH.
    # If it broke a swing LOW (Direction.DOWN), the MSB is BEARISH.
    msb_is_bullish = msb_pivot.direction == Direction.UP
    
    # Check EMA50 slope veto (Resolution I-2)
    ind_state = get_indicator_state(asset, timeframe)
    current_ema = ind_state.ema_50
    lagged_ema = ema_50_at_lag(asset, timeframe, EMA50_SLOPE_LAG_BARS)
    
    if current_ema and lagged_ema:
        ema_is_bullish = current_ema > lagged_ema
        ema_is_bearish = current_ema < lagged_ema
        
        # Conflict check
        if msb_is_bullish and ema_is_bearish:
            htf_bias[asset] = BiasState.NEUTRAL
            return
        if not msb_is_bullish and ema_is_bullish:
            htf_bias[asset] = BiasState.NEUTRAL
            return
            
    # If no conflict (or EMA not warmed up yet), assign bias based on MSB
    htf_bias[asset] = BiasState.BULLISH if msb_is_bullish else BiasState.BEARISH
