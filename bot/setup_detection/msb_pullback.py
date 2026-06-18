from typing import List
from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import (
    SHALLOW_FIB_MIN, SHALLOW_FIB_MAX, SHALLOW_ATR_CAP_MULT,
    DEEP_FIB_MIN, DEEP_FIB_MAX, MIN_STOP_ATR_MULT
)
from bot.setup_detection.clean_break import detect_clean_break

def detect_msb_pullback(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float,
    lookback_bars: int = 20
) -> List[SetupCandidate]:
    """
    Detects Shallow and Deep Pullback setups following an MSB.
    
    1. Identify a recent clean break of a major pivot (the MSB).
    2. Identify the swing origin (most recent opposite pivot before the break).
    3. Identify the swing extreme (max high or min low since the origin).
    4. Calculate Fib retracement of the recent pullback.
    5. Check if it falls into SHALLOW or DEEP bands and resolves (bounces).
    """
    candidates = []
    
    if len(bars) < 2 or not pivots or atr <= 0:
        return candidates
        
    current_bar = bars[-1]
    
    for pivot in reversed(pivots):
        if pivot.timestamp >= current_bar.timestamp:
            continue
            
        bars_since = [b for b in bars if b.timestamp > pivot.timestamp]
        if len(bars_since) > lookback_bars:
            continue
            
        break_dir = None
        break_idx = -1
        
        for i, b in enumerate(bars_since):
            if pivot.direction == Direction.UP and b.close > pivot.price:
                if detect_clean_break(b, pivot.price, Direction.UP, atr):
                    break_dir = Direction.UP
                    break_idx = i
                    break
            elif pivot.direction == Direction.DOWN and b.close < pivot.price:
                if detect_clean_break(b, pivot.price, Direction.DOWN, atr):
                    break_dir = Direction.DOWN
                    break_idx = i
                    break
                    
        if break_dir is None or break_idx == len(bars_since) - 1:
            continue
            
        # Find the swing origin (the opposite pivot prior to the broken pivot)
        origin_pivot = None
        for p in reversed(pivots):
            if p.timestamp < pivot.timestamp and p.direction != pivot.direction:
                origin_pivot = p
                break
                
        if not origin_pivot:
            continue
            
        bars_since_origin = [b for b in bars if origin_pivot.timestamp <= b.timestamp <= current_bar.timestamp]
        
        if break_dir == Direction.UP:
            if current_bar.close <= current_bar.open:
                continue # Must be a bounce
                
            # Find the highest point of the swing (prior to current_bar)
            swing_high = -999999.0
            swing_high_idx = -1
            for idx, b in enumerate(bars_since_origin[:-1]):
                if b.high > swing_high:
                    swing_high = b.high
                    swing_high_idx = idx
                    
            pullback_bars = bars_since_origin[swing_high_idx+1:]
            if not pullback_bars:
                continue
                
            pullback_low = min(b.low for b in pullback_bars)
            total_swing = swing_high - origin_pivot.price
            
            if total_swing <= 0:
                continue
                
            pullback_size = swing_high - pullback_low
            fib = pullback_size / total_swing
            
            setup_type = None
            if SHALLOW_FIB_MIN <= fib <= SHALLOW_FIB_MAX:
                if pullback_size <= SHALLOW_ATR_CAP_MULT * atr:
                    setup_type = SetupType.MSB_SHALLOW
            elif DEEP_FIB_MIN <= fib <= DEEP_FIB_MAX:
                setup_type = SetupType.MSB_DEEP
                
            if setup_type:
                stop_price = pullback_low - (MIN_STOP_ATR_MULT * atr)
                cand = SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=setup_type,
                    setup_class=SetupClass.CONTINUATION,
                    direction=Direction.UP,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars)-1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )
                candidates.append(cand)
                break
                
        else: # DOWN break
            if current_bar.close >= current_bar.open:
                continue
                
            swing_low = 999999.0
            swing_low_idx = -1
            for idx, b in enumerate(bars_since_origin[:-1]):
                if b.low < swing_low:
                    swing_low = b.low
                    swing_low_idx = idx
                    
            pullback_bars = bars_since_origin[swing_low_idx+1:]
            if not pullback_bars:
                continue
                
            pullback_high = max(b.high for b in pullback_bars)
            total_swing = origin_pivot.price - swing_low
            
            if total_swing <= 0:
                continue
                
            pullback_size = pullback_high - swing_low
            fib = pullback_size / total_swing
            
            setup_type = None
            if SHALLOW_FIB_MIN <= fib <= SHALLOW_FIB_MAX:
                if pullback_size <= SHALLOW_ATR_CAP_MULT * atr:
                    setup_type = SetupType.MSB_SHALLOW
            elif DEEP_FIB_MIN <= fib <= DEEP_FIB_MAX:
                setup_type = SetupType.MSB_DEEP
                
            if setup_type:
                stop_price = pullback_high + (MIN_STOP_ATR_MULT * atr)
                cand = SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=setup_type,
                    setup_class=SetupClass.CONTINUATION,
                    direction=Direction.DOWN,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars)-1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )
                candidates.append(cand)
                break
                
    return candidates
