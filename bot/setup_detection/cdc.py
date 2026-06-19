from typing import List
from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass
)
from bot.config import (
    CDC_NO_INTERACTION_ATR_MULT, SR_FLIP_STOP_ATR_MULT,
    CDC_CONFIRM_ATR_MULT, CDC_BODY_RATIO_MIN
)
from bot.setup_detection.clean_break import detect_clean_break

def detect_cdc(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float, 
    include_pattern_failure: bool = False,
    lookback_bars: int = 20
) -> List[SetupCandidate]:
    """
    Detects CDC (Clean-Break, Drift, Close) and Pattern Failure setups.
    
    A CDC setup is formed when:
    1. A major pivot is cleanly broken.
    2. Price drifts back toward the pivot but does not interact with it deeply 
       (intrusion <= CDC_NO_INTERACTION_ATR_MULT * atr).
    3. Price closes back in the direction of the break.
    
    A Pattern Failure setup (if include_pattern_failure=True) is formed when:
    1. A major pivot is cleanly broken.
    2. Price drifts back and cleanly breaks the pivot in the *opposite* direction.
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
            
        drift_bars = bars_since[break_idx+1:]
        
        drift_started = False
        max_intrusion = -999999.0
        
        for b in drift_bars:
            if break_dir == Direction.UP:
                current_intrusion = pivot.price - b.low
                
                if include_pattern_failure and detect_clean_break(b, pivot.price, Direction.DOWN, atr):
                    stop_price = pivot.price + (SR_FLIP_STOP_ATR_MULT * atr)
                    cand = SetupCandidate(
                        asset=current_bar.asset,
                        timeframe=current_bar.timeframe,
                        setup_type=SetupType.PATTERN_FAILURE,
                        setup_class=SetupClass.TRAP,
                        direction=Direction.DOWN,
                        trigger_pivot=pivot,
                        detected_at=b.timestamp,
                        detected_bar_index=bars.index(b),
                        trigger_price=b.close,
                        stop_price=stop_price,
                        is_pattern_failure_mode=True,
                        cdc_qualifies_zero_tolerance=(max_intrusion <= 0)
                    )
                    candidates.append(cand)
                    break
                    
                max_intrusion = max(max_intrusion, current_intrusion)
                
                if current_intrusion > CDC_NO_INTERACTION_ATR_MULT * atr:
                    break # Invalidated, stop evaluating this pivot
                    
                if drift_started and b.close > b.open:
                    body = b.close - b.open
                    rng = b.high - b.low
                    if body >= CDC_CONFIRM_ATR_MULT * atr and (rng == 0 or (body / rng) >= CDC_BODY_RATIO_MIN):
                        stop_price = pivot.price - (SR_FLIP_STOP_ATR_MULT * atr)
                        cand = SetupCandidate(
                            asset=current_bar.asset,
                            timeframe=current_bar.timeframe,
                            setup_type=SetupType.CDC,
                            setup_class=SetupClass.TRAP,
                            direction=Direction.UP,
                            trigger_pivot=pivot,
                            detected_at=b.timestamp,
                            detected_bar_index=bars.index(b),
                            trigger_price=b.close,
                            stop_price=stop_price,
                            is_pattern_failure_mode=False,
                            cdc_qualifies_zero_tolerance=(max_intrusion <= 0)
                        )
                        candidates.append(cand)
                        break
                    
                if b.close < b.open:
                    drift_started = True
                    
            else: # break_dir == Direction.DOWN
                current_intrusion = b.high - pivot.price
                
                if include_pattern_failure and detect_clean_break(b, pivot.price, Direction.UP, atr):
                    stop_price = pivot.price - (SR_FLIP_STOP_ATR_MULT * atr)
                    cand = SetupCandidate(
                        asset=current_bar.asset,
                        timeframe=current_bar.timeframe,
                        setup_type=SetupType.PATTERN_FAILURE,
                        setup_class=SetupClass.TRAP,
                        direction=Direction.UP,
                        trigger_pivot=pivot,
                        detected_at=b.timestamp,
                        detected_bar_index=bars.index(b),
                        trigger_price=b.close,
                        stop_price=stop_price,
                        is_pattern_failure_mode=True,
                        cdc_qualifies_zero_tolerance=(max_intrusion <= 0)
                    )
                    candidates.append(cand)
                    break
                    
                max_intrusion = max(max_intrusion, current_intrusion)
                
                if current_intrusion > CDC_NO_INTERACTION_ATR_MULT * atr:
                    break
                    
                if drift_started and b.close < b.open:
                    body = b.open - b.close
                    rng = b.high - b.low
                    if body >= CDC_CONFIRM_ATR_MULT * atr and (rng == 0 or (body / rng) >= CDC_BODY_RATIO_MIN):
                        stop_price = pivot.price + (SR_FLIP_STOP_ATR_MULT * atr)
                        cand = SetupCandidate(
                            asset=current_bar.asset,
                            timeframe=current_bar.timeframe,
                            setup_type=SetupType.CDC,
                            setup_class=SetupClass.TRAP,
                            direction=Direction.DOWN,
                            trigger_pivot=pivot,
                            detected_at=b.timestamp,
                            detected_bar_index=bars.index(b),
                            trigger_price=b.close,
                            stop_price=stop_price,
                            is_pattern_failure_mode=False,
                            cdc_qualifies_zero_tolerance=(max_intrusion <= 0)
                        )
                        candidates.append(cand)
                        break
                    
                if b.close > b.open:
                    drift_started = True
                    
    # Only return candidates that fired exactly on the current_bar
    return [c for c in candidates if c.detected_at == current_bar.timestamp]
