from typing import List, Optional
from datetime import datetime

from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import SR_FLIP_STOP_ATR_MULT, SR_FLIP_PULLBACK_ATR_TOL
from bot.setup_detection.clean_break import detect_clean_break

def detect_sr_flip(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float,
    lookback_bars: int = 20
) -> List[SetupCandidate]:
    """
    Detects a Support/Resistance Flip setup.
    
    Logic:
    1. Look for a major pivot within the lookback window.
    2. Ensure the pivot was 'cleanly broken' by a subsequent candle (detect_clean_break).
    3. Ensure the current candle (or recent candles) pulled back to the broken pivot.
    4. Confirm a bounce (current bar closes in the flip direction).
    """
    if len(bars) < 2 or not pivots or atr <= 0:
        return []
        
    current_bar = bars[-1]
    
    # Check each pivot (newest first)
    for pivot in reversed(pivots):
        if pivot.timestamp >= current_bar.timestamp:
            continue
            
        # Isolate bars since this pivot
        bars_since_pivot = [b for b in bars if b.timestamp > pivot.timestamp]
        if len(bars_since_pivot) > lookback_bars:
            continue # Pivot is too old
            
        # Look for a clean break of this pivot
        break_idx = -1
        break_dir = None
        for i, b in enumerate(bars_since_pivot):
            if pivot.direction == Direction.UP and b.close > pivot.price:
                # Potential clean break UP (Resistance broken, becomes Support)
                if detect_clean_break(b, pivot.price, Direction.UP, atr):
                    break_idx = i
                    break_dir = Direction.UP
                    break
            elif pivot.direction == Direction.DOWN and b.close < pivot.price:
                # Potential clean break DOWN (Support broken, becomes Resistance)
                if detect_clean_break(b, pivot.price, Direction.DOWN, atr):
                    break_idx = i
                    break_dir = Direction.DOWN
                    break
                    
        if break_idx == -1 or break_idx == len(bars_since_pivot) - 1:
            # Not broken, or just broken on the current bar (no time for pullback)
            continue
            
        # Has price touched the pivot again after the break?
        bars_since_break = bars_since_pivot[break_idx+1:]
        
        pulled_back = False
        for b in bars_since_break:
            if break_dir == Direction.UP:
                # Price should drop back down to the pivot
                if b.low <= pivot.price + (SR_FLIP_PULLBACK_ATR_TOL * atr):
                    pulled_back = True
            else:
                # Price should rise back up to the pivot
                if b.high >= pivot.price - (SR_FLIP_PULLBACK_ATR_TOL * atr):
                    pulled_back = True
                    
        if not pulled_back:
            continue
            
        # Trigger condition: current bar closes in the direction of the new trend
        if break_dir == Direction.UP:
            # Long setup
            if current_bar.close > current_bar.open and current_bar.close > pivot.price:
                # Part V: SR_FLIP_STOP_ATR_MULT for eventual stop reference
                stop_price = pivot.price - (SR_FLIP_STOP_ATR_MULT * atr)
                return [SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=SetupType.SR_FLIP,
                    setup_class=SetupClass.CONTINUATION,
                    direction=Direction.UP,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars) - 1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )]
        else:
            # Short setup
            if current_bar.close < current_bar.open and current_bar.close < pivot.price:
                stop_price = pivot.price + (SR_FLIP_STOP_ATR_MULT * atr)
                return [SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=SetupType.SR_FLIP,
                    setup_class=SetupClass.CONTINUATION,
                    direction=Direction.DOWN,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars) - 1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )]
                
    return []
