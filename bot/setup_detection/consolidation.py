from typing import List, Tuple
from bot.structs import (
    OHLCV_Bar, SetupCandidate, SetupType, SetupClass, Direction
)
from bot.config import (
    CONSOLIDATION_MIN_BARS,
    CONSOLIDATION_BAR_RANGE_ATR_MULT,
    CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT,
    MIN_STOP_ATR_MULT
)
from bot.setup_detection.clean_break import detect_clean_break

def detect_consolidation(
    bars: List[OHLCV_Bar],
    atr: float
) -> List[SetupCandidate]:
    """
    Detects Consolidation Breakout setups.
    
    A consolidation phase is identified by:
    1. At least CONSOLIDATION_MIN_BARS consecutive bars.
    2. Each bar's range (H - L) < CONSOLIDATION_BAR_RANGE_ATR_MULT * atr.
    3. The total height of the zone (max high - min low) < CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT * atr.
    
    The setup fires if the current bar cleanly breaks out of this zone.
    """
    candidates = []
    
    if len(bars) < CONSOLIDATION_MIN_BARS + 1 or atr <= 0:
        return candidates
        
    current_bar = bars[-1]
    
    # We look backwards to find a valid consolidation zone immediately preceding the current bar.
    # To be robust, we find the longest sequence of bars ending at bars[-2] that satisfies the conditions.
    # We just need to find AT LEAST CONSOLIDATION_MIN_BARS.
    
    consolidation_zone = []
    
    for b in reversed(bars[:-1]):
        bar_range = b.high - b.low
        if bar_range >= CONSOLIDATION_BAR_RANGE_ATR_MULT * atr:
            break
            
        consolidation_zone.append(b)
        
        # Check total height
        max_high = max(cb.high for cb in consolidation_zone)
        min_low = min(cb.low for cb in consolidation_zone)
        total_height = max_high - min_low
        
        if total_height >= CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT * atr:
            # The current bar broke the total height constraint, so the zone ends BEFORE this bar.
            # Pop the offending bar and break
            consolidation_zone.pop()
            break
            
    if len(consolidation_zone) < CONSOLIDATION_MIN_BARS:
        return candidates
        
    # We have a valid consolidation zone.
    zone_high = max(cb.high for cb in consolidation_zone)
    zone_low = min(cb.low for cb in consolidation_zone)
    
    # Check if current_bar breaks out
    # Breakout UP
    if current_bar.close > zone_high:
        if detect_clean_break(current_bar, zone_high, Direction.UP, atr):
            stop_price = current_bar.low - (MIN_STOP_ATR_MULT * atr)
            cand = SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.CONSOLIDATION_ENTRY,
                setup_class=SetupClass.CONTINUATION, # Can be either, default to continuation
                direction=Direction.UP,
                trigger_pivot=None, # Consolidation breakout doesn't strictly need a pivot
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars)-1,
                trigger_price=current_bar.close,
                stop_price=stop_price
            )
            candidates.append(cand)
            
    # Breakout DOWN
    elif current_bar.close < zone_low:
        if detect_clean_break(current_bar, zone_low, Direction.DOWN, atr):
            stop_price = current_bar.high + (MIN_STOP_ATR_MULT * atr)
            cand = SetupCandidate(
                asset=current_bar.asset,
                timeframe=current_bar.timeframe,
                setup_type=SetupType.CONSOLIDATION_ENTRY,
                setup_class=SetupClass.CONTINUATION,
                direction=Direction.DOWN,
                trigger_pivot=None,
                detected_at=current_bar.timestamp,
                detected_bar_index=len(bars)-1,
                trigger_price=current_bar.close,
                stop_price=stop_price
            )
            candidates.append(cand)
            
    return candidates
