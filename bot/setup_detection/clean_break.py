from bot.structs import OHLCV_Bar, Direction
from bot.config import BREAK_BODY_ATR_MULT, BREAK_CLOSE_BEYOND_ATR_MULT, BREAK_WICK_RATIO_MAX

def detect_clean_break(bar: OHLCV_Bar, level: float, direction: Direction, atr: float) -> bool:
    """
    Evaluates if a single candle cleanly breaks a price level.
    Uses Proxy A + C composite logic:
      A: Candle body spans >= BREAK_BODY_ATR_MULT * ATR
         Close is >= BREAK_CLOSE_BEYOND_ATR_MULT * ATR beyond the level
      C: Rejection wick (top for up break, bottom for down) / total range <= BREAK_WICK_RATIO_MAX
    """
    if atr <= 0:
        return False
        
    candle_range = bar.high - bar.low
    if candle_range <= 0:
        return False
        
    body_size = abs(bar.close - bar.open)
    if body_size < BREAK_BODY_ATR_MULT * atr:
        return False
        
    if direction == Direction.UP:
        # Breaking resistance
        if bar.close <= level:
            return False
            
        if (bar.close - level) < BREAK_CLOSE_BEYOND_ATR_MULT * atr:
            return False
            
        top_wick = bar.high - max(bar.open, bar.close)
        if (top_wick / candle_range) > BREAK_WICK_RATIO_MAX:
            return False
            
    else:
        # Breaking support
        if bar.close >= level:
            return False
            
        if (level - bar.close) < BREAK_CLOSE_BEYOND_ATR_MULT * atr:
            return False
            
        bottom_wick = min(bar.open, bar.close) - bar.low
        if (bottom_wick / candle_range) > BREAK_WICK_RATIO_MAX:
            return False
            
    return True
