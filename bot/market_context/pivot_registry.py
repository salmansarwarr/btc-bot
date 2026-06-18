"""
pivot_registry.py — Pivot detection and registry
=================================================

**Spec reference:** Doc-3 update_pivot_registry; Doc-2 §3, §4.
Resolution II-1: percentile filter applied at scoring time (conviction), not detection.
Resolution II-2: first_reaction_confirmed tracked here.
"""
from __future__ import annotations
from datetime import datetime
from typing import Dict, List, Optional

from bot.structs import PivotFlag, PivotStrength, Direction
from bot.config import (
    PIVOT_MAJOR_N, PIVOT_MINOR_N, PIVOT_MAJOR_ATR_MULT,
)
from bot.data_ingestion.ohlcv_buffer import get_bars
from bot.indicators.registry import get_or_create as get_indicator_state

pivot_registry: Dict[str, Dict[str, List[PivotFlag]]] = {}

def _ensure(asset: str, timeframe: str) -> None:
    if asset not in pivot_registry:
        pivot_registry[asset] = {}
    if timeframe not in pivot_registry[asset]:
        pivot_registry[asset][timeframe] = []


def update_pivot_registry(asset: str, timeframe: str) -> None:
    """
    Run N-candle fractal detection on the latest bar close.
    Because a fractal requires N bars *after* the pivot, we evaluate the bar
    that closed N periods ago.
    """
    _ensure(asset, timeframe)
    
    # Determine N for MAJOR and MINOR on this timeframe
    major_n = PIVOT_MAJOR_N.get(timeframe, PIVOT_MAJOR_N["default"])
    minor_n = PIVOT_MINOR_N
    
    max_n = max(major_n, minor_n)
    
    # We need 2*max_n + 1 bars to detect a fractal
    bars = get_bars(asset, timeframe, 2 * max_n + 1)
    if len(bars) < 2 * max_n + 1:
        return
        
    current_bar_idx = len(get_bars(asset, timeframe, 100000)) - 1  # Approximate total index
    
    # Evaluate for major
    _check_and_add_fractal(asset, timeframe, bars, current_bar_idx, major_n, PivotStrength.MAJOR)
    
    # Evaluate for minor
    # A bar could be both a major and minor fractal, but we only store the highest strength.
    # If it was already added as MAJOR, we don't add it as MINOR.
    _check_and_add_fractal(asset, timeframe, bars, current_bar_idx, minor_n, PivotStrength.MINOR)


def _check_and_add_fractal(
    asset: str, 
    timeframe: str, 
    bars: List, 
    current_idx: int, 
    n: int, 
    strength: PivotStrength
) -> None:
    # The candidate bar is N bars from the end
    # e.g., if N=2, bars[-3] is the candidate
    candidate_idx_in_window = len(bars) - 1 - n
    candidate = bars[candidate_idx_in_window]
    
    # Check High Fractal
    is_high = True
    for i in range(len(bars)):
        if i == candidate_idx_in_window:
            continue
        # Only check within the local window [-N, +N] around candidate
        if abs(i - candidate_idx_in_window) <= n:
            if bars[i].high >= candidate.high:
                is_high = False
                break
                
    # Check Low Fractal
    is_low = True
    for i in range(len(bars)):
        if i == candidate_idx_in_window:
            continue
        if abs(i - candidate_idx_in_window) <= n:
            if bars[i].low <= candidate.low:
                is_low = False
                break
                
    direction = None
    pivot_price = 0.0
    
    if is_high:
        direction = Direction.UP
        pivot_price = candidate.high
    elif is_low:
        direction = Direction.DOWN
        pivot_price = candidate.low
    else:
        return  # Not a fractal
        
    # Get ATR for size gating
    ind_state = get_indicator_state(asset, timeframe)
    atr = ind_state.atr_14
    
    # If MAJOR, check size gate
    if strength == PivotStrength.MAJOR and atr > 0:
        # We look at the preceding swing size. For simplicity here, we assume 
        # the size gate is passed if it's visually prominent, but strictly:
        # "range qualifies by PIVOT_MAJOR_ATR_MULT"
        # We will approximate swing size by comparing to the lowest low / highest high 
        # in the N window.
        local_min = min(b.low for b in bars[candidate_idx_in_window-n:candidate_idx_in_window+n+1])
        local_max = max(b.high for b in bars[candidate_idx_in_window-n:candidate_idx_in_window+n+1])
        swing_size = local_max - local_min
        if swing_size < PIVOT_MAJOR_ATR_MULT * atr:
            return  # Fails size gate
            
    # Avoid duplicate pivots at the same timestamp
    existing = [p for p in pivot_registry[asset][timeframe] if p.timestamp == candidate.timestamp]
    if existing:
        if existing[0].strength == PivotStrength.MINOR and strength == PivotStrength.MAJOR:
            existing[0].strength = PivotStrength.MAJOR  # Upgrade strength
        return
        
    global_idx = current_idx - n
    pivot = PivotFlag(
        asset=asset,
        timeframe=timeframe,
        price=pivot_price,
        direction=direction,
        strength=strength,
        bar_index=global_idx,
        timestamp=candidate.timestamp,
        first_reaction_confirmed=False
    )
    pivot_registry[asset][timeframe].append(pivot)


def check_first_reaction(asset: str, timeframe: str) -> None:
    """
    For each MINOR pivot, check if price approached and reversed >= 0.25*ATR(14) on first contact.
    Resolution II-2.
    """
    _ensure(asset, timeframe)
    bars = get_bars(asset, timeframe, 2)
    if len(bars) < 1:
        return
        
    latest_bar = bars[-1]
    ind_state = get_indicator_state(asset, timeframe)
    atr = ind_state.atr_14
    if atr <= 0:
        return
        
    for pivot in pivot_registry[asset][timeframe]:
        if pivot.strength != PivotStrength.MINOR or pivot.first_reaction_confirmed:
            continue
            
        # "Approached": crossed or came very close. We'll define "approach" as within 0.1 ATR.
        approach_dist = 0.1 * atr
        reversal_req = 0.25 * atr
        
        if pivot.direction == Direction.UP:
            # Resistance pivot. Approached from below.
            if latest_bar.high >= pivot.price - approach_dist:
                # Did it reverse by 0.25 ATR from the high?
                if latest_bar.high - latest_bar.close >= reversal_req:
                    pivot.first_reaction_confirmed = True
        else:
            # Support pivot. Approached from above.
            if latest_bar.low <= pivot.price + approach_dist:
                if latest_bar.close - latest_bar.low >= reversal_req:
                    pivot.first_reaction_confirmed = True
