import math
from bot.structs import SetupCandidate, SetupType, Direction
from bot.config import SR_FLIP_STOP_ATR_MULT, MIN_STOP_ATR_MULT
from bot.indicators.registry import get_or_create

def compute_stop(candidate: SetupCandidate, atr: float = None) -> float:
    """
    Return the initial stop price for a setup.
    Method depends on setup_type:
      SR_FLIP setups: pivot_price ± SR_FLIP_STOP_ATR_MULT × ATR(14). (I-4)
      MSB setups: below/above the MSB origin pivot.
      Fallback: entry_price ± MIN_STOP_ATR_MULT × ATR(14).
    Stop is always at least MIN_STOP_ATR_MULT × ATR(14) from entry.
    """
    if atr is None:
        state = get_or_create(candidate.asset, candidate.timeframe)
        atr = state.atr_14
        if atr is None or math.isnan(atr):
            atr = 0.0

    min_offset = MIN_STOP_ATR_MULT * atr
    
    stop_price = 0.0
    
    if candidate.setup_type == SetupType.SR_FLIP and candidate.trigger_pivot is not None:
        offset = SR_FLIP_STOP_ATR_MULT * atr
        if candidate.direction == Direction.UP:
            stop_price = candidate.trigger_pivot.price - offset
        else:
            stop_price = candidate.trigger_pivot.price + offset
            
    elif candidate.setup_type in (SetupType.MSB_SHALLOW, SetupType.MSB_DEEP) and candidate.trigger_pivot is not None:
        if candidate.direction == Direction.UP:
            # Below MSB origin pivot
            stop_price = candidate.trigger_pivot.price - min_offset
        else:
            # Above MSB origin pivot
            stop_price = candidate.trigger_pivot.price + min_offset
            
    else:
        # Fallback for CLEAN_BREAK, SFP, OPEN_DRIVE, CONSOLIDATION_ENTRY, MOMENTUM_DIVERGENCE, LIQUIDATION_FLUSH, CDC, PATTERN_FAILURE
        if candidate.direction == Direction.UP:
            stop_price = candidate.trigger_price - min_offset
        else:
            stop_price = candidate.trigger_price + min_offset

    # Enforce constraint: Stop is always at least MIN_STOP_ATR_MULT × ATR(14) from entry
    if candidate.direction == Direction.UP:
        max_allowed_stop = candidate.trigger_price - min_offset
        stop_price = min(stop_price, max_allowed_stop)
    else:
        min_allowed_stop = candidate.trigger_price + min_offset
        stop_price = max(stop_price, min_allowed_stop)

    return stop_price
