from typing import List
from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import MIN_STOP_ATR_MULT, SFP_WICK_ATR_MULT, ENABLE_SFP

def detect_sfp(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float,
    lookback_bars: int = 20
) -> List[SetupCandidate]:
    """
    Detects Swing Failure Pattern (SFP) setups.
    
    Trigger: price wicks beyond a pivot then closes back inside.
    The level must not have been previously broken (closed beyond).
    SetupType = SFP, SetupClass = TRAP.
    """
    if not ENABLE_SFP:
        return []
    
    candidates = []
    if not bars or not pivots or atr <= 0:
        return candidates
        
    current_bar = bars[-1]
    
    for pivot in reversed(pivots):
        if pivot.timestamp >= current_bar.timestamp:
            continue
            
        # Is pivot within the lookback window?
        bars_since = [b for b in bars if b.timestamp > pivot.timestamp]
        if len(bars_since) > lookback_bars:
            continue
            
        # Ensure the pivot has not been closed beyond previously
        broken = False
        for b in bars_since[:-1]:
            if pivot.direction == Direction.UP and b.close > pivot.price:
                broken = True
                break
            elif pivot.direction == Direction.DOWN and b.close < pivot.price:
                broken = True
                break
                
        if broken:
            continue
            
        if pivot.direction == Direction.UP: # Resistance pivot
            # SFP Short: Sweeps the resistance, but closes below it.
            wick_size = current_bar.high - max(current_bar.open, current_bar.close)
            if current_bar.high > pivot.price and current_bar.close <= pivot.price and wick_size >= (SFP_WICK_ATR_MULT * atr):
                # Stop is placed just above the wick
                stop_price = current_bar.high + (MIN_STOP_ATR_MULT * atr)
                cand = SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=SetupType.SFP,
                    setup_class=SetupClass.TRAP,
                    direction=Direction.DOWN,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars)-1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )
                candidates.append(cand)
                break
                
        else: # Support pivot (DOWN)
            # SFP Long: Sweeps the support, but closes above it.
            wick_size = min(current_bar.open, current_bar.close) - current_bar.low
            if current_bar.low < pivot.price and current_bar.close >= pivot.price and wick_size >= (SFP_WICK_ATR_MULT * atr):
                stop_price = current_bar.low - (MIN_STOP_ATR_MULT * atr)
                cand = SetupCandidate(
                    asset=current_bar.asset,
                    timeframe=current_bar.timeframe,
                    setup_type=SetupType.SFP,
                    setup_class=SetupClass.TRAP,
                    direction=Direction.UP,
                    trigger_pivot=pivot,
                    detected_at=current_bar.timestamp,
                    detected_bar_index=len(bars)-1,
                    trigger_price=current_bar.close,
                    stop_price=stop_price
                )
                candidates.append(cand)
                break
                
    return candidates
