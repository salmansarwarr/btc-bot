from typing import List
from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import (
    DRIVE_ATR_MULT, DRIVE_BODY_RANGE_RATIO_MIN, MIN_STOP_ATR_MULT
)

def detect_open_drive(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float,
    lookback_bars: int = 20
) -> List[SetupCandidate]:
    """
    Detects Candle Open Drive setups.
    
    A Candle Open Drive is a strong directional candle that:
    1. Moves >= DRIVE_ATR_MULT * ATR from open (body size).
    2. Body / total range >= DRIVE_BODY_RANGE_RATIO_MIN.
    3. Originates near a major pivot (opens near it or breaks it).
    """
    candidates = []
    
    if not bars or not pivots or atr <= 0:
        return candidates
        
    current_bar = bars[-1]
    body = abs(current_bar.close - current_bar.open)
    candle_range = current_bar.high - current_bar.low
    
    if candle_range <= 0:
        return candidates
        
    # Check Proxy A conditions for Open Drive
    if body < DRIVE_ATR_MULT * atr:
        return candidates
        
    if body / candle_range < DRIVE_BODY_RANGE_RATIO_MIN:
        return candidates
        
    drive_direction = Direction.UP if current_bar.close > current_bar.open else Direction.DOWN
    
    # Check if the drive originates from or breaks a recent pivot
    for pivot in reversed(pivots):
        if pivot.timestamp >= current_bar.timestamp:
            continue
            
        # Is pivot within the lookback window?
        # We estimate lookback by assuming each bar is 1 timeframe unit, but it's simpler
        # to just check if it's within the last `lookback_bars` bars.
        # Since we don't have exact bar indices for the pivot relative to current_bar easily,
        # we can just use a time approximation or if it's in the recent bars.
        bars_since = [b for b in bars if b.timestamp > pivot.timestamp]
        if len(bars_since) > lookback_bars:
            continue
            
        # We look for two cases:
        # 1. Drive bounces off the pivot (opens near it and drives away).
        # 2. Drive breaks the pivot (opens before it, closes after it).
        
        interacts = False
        proximity = abs(current_bar.open - pivot.price)
        
        # Bouncing off the pivot (Open is near the pivot)
        if proximity <= MIN_STOP_ATR_MULT * atr:
            # If it's a Support pivot and we drive UP, or Resistance and we drive DOWN
            if pivot.direction != drive_direction:
                interacts = True
                
        # Breaking the pivot
        if not interacts:
            if drive_direction == Direction.UP and pivot.direction == Direction.UP:
                if current_bar.open <= pivot.price and current_bar.close > pivot.price:
                    interacts = True
            elif drive_direction == Direction.DOWN and pivot.direction == Direction.DOWN:
                if current_bar.open >= pivot.price and current_bar.close < pivot.price:
                    interacts = True
                    
        if interacts:
            if drive_direction == Direction.UP:
                stop_price = current_bar.low - (MIN_STOP_ATR_MULT * atr)
            else:
                stop_price = current_bar.high + (MIN_STOP_ATR_MULT * atr)
                
            cand = SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.OPEN_DRIVE,
                setup_class=SetupClass.CONTINUATION if pivot.direction == drive_direction else SetupClass.REVERSAL,
                direction=drive_direction,
                trigger_pivot=pivot,
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars)-1,
                trigger_price=current_bar.close,
                stop_price=stop_price
            )
            candidates.append(cand)
            break # Only trigger once per bar
            
    return candidates
