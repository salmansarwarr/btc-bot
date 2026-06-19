from typing import List, Optional
from datetime import datetime

from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import (
    SR_FLIP_STOP_ATR_MULT, SR_FLIP_PULLBACK_ATR_TOL,
    FLIP_CONFIRM_BARS, FLIP_ATR_MULT, FLIP_BODY_RATIO_MIN
)
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
    3. Ensure the price pulled back to the broken pivot.
    4. Confirm a bounce (last FLIP_CONFIRM_BARS close in the flip direction with sufficient conviction).
    """
    if len(bars) < max(2, FLIP_CONFIRM_BARS) or not pivots or atr <= 0:
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
            
        # Trigger condition: last FLIP_CONFIRM_BARS close in the direction of the new trend
        confirm_bars = bars[-FLIP_CONFIRM_BARS:] if FLIP_CONFIRM_BARS > 0 else [current_bar]
        
        valid_confirm = True
        for b in confirm_bars:
            body_size = abs(b.close - b.open)
            total_range = b.high - b.low
            
            if break_dir == Direction.UP:
                if b.close <= b.open or b.close <= pivot.price:
                    valid_confirm = False
                    break
            else:
                if b.close >= b.open or b.close >= pivot.price:
                    valid_confirm = False
                    break
                    
            if body_size < (FLIP_ATR_MULT * atr):
                valid_confirm = False
                break
                
            if total_range > 0:
                if (body_size / total_range) < FLIP_BODY_RATIO_MIN:
                    valid_confirm = False
                    break
            elif FLIP_BODY_RATIO_MIN > 0:
                valid_confirm = False
                break
                
        if valid_confirm:
            stop_mult = SR_FLIP_STOP_ATR_MULT * atr
            stop_price = pivot.price - stop_mult if break_dir == Direction.UP else pivot.price + stop_mult
            return [SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.SR_FLIP,
                setup_class=SetupClass.CONTINUATION,
                direction=break_dir,
                trigger_pivot=pivot,
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars) - 1,
                trigger_price=current_bar.close,
                stop_price=stop_price
            )]
                
    return []

