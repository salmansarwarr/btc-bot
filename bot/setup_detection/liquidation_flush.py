import statistics
from typing import List, Optional

from bot.structs import (
    OHLCV_Bar, PivotFlag, Direction, SetupCandidate, SetupType, SetupClass,
    ExternalFeedState, AssetConfig, LiquidationProxyMethod
)
from bot.config import (
    LIQ_SIGMA_THRESHOLD, LIQ_PERCENTILE_THRESHOLD, LIQ_OI_PCT_THRESHOLD,
    MIN_STOP_ATR_MULT
)

def compute_asset_liquidation_zscore(asset: str) -> float:
    """Stub — replaced by direct calculation in detect_liquidation_flush to avoid globals."""
    raise NotImplementedError

def detect_liquidation_flush(
    bars: List[OHLCV_Bar], 
    pivots: List[PivotFlag], 
    atr: float,
    config: AssetConfig,
    feed: ExternalFeedState
) -> List[SetupCandidate]:
    """
    Detects Liquidation Flush setups.
    
    1. Checks for a massive liquidation spike using Proxy C, B, or A based on config.
    2. If a spike is detected, looks for a reversal candle.
    3. Attaches a trigger_pivot if the flush bounced off a nearby major pivot.
    """
    candidates = []
    
    if not bars or not feed or not feed.liq_hourly or not feed.oi_hourly:
        return candidates
        
    is_spike = False
    method = config.liquidation_proxy_method
    current_liq = feed.liq_hourly[-1]
    
    if method == LiquidationProxyMethod.OI_PCT:
        if len(feed.oi_hourly) >= 2:
            prev_oi = feed.oi_hourly[-2]
            if prev_oi > 0:
                if current_liq / prev_oi >= LIQ_OI_PCT_THRESHOLD:
                    is_spike = True
                    
    elif method == LiquidationProxyMethod.PERCENTILE:
        if len(feed.liq_hourly) > 20: # Ensure we have some history
            history = sorted(feed.liq_hourly[:-1])
            idx = int(len(history) * LIQ_PERCENTILE_THRESHOLD)
            threshold = history[idx] if idx < len(history) else history[-1]
            if current_liq >= threshold:
                is_spike = True
                
    elif method == LiquidationProxyMethod.ZSCORE:
        if len(feed.liq_hourly) > 3:
            window = feed.liq_hourly[-480:-1] if len(feed.liq_hourly) > 480 else feed.liq_hourly[:-1]
            if len(window) > 2:
                mean = statistics.mean(window)
                std = statistics.stdev(window)
                if std > 0:
                    zscore = (current_liq - mean) / std
                    if zscore >= LIQ_SIGMA_THRESHOLD:
                        is_spike = True
                        
    if not is_spike:
        return candidates
        
    current_bar = bars[-1]
    bottom_wick = min(current_bar.open, current_bar.close) - current_bar.low
    top_wick = current_bar.high - max(current_bar.open, current_bar.close)
    
    # Direction is UP (Long) if the bottom wick is larger (price dumped and rejected)
    direction = Direction.UP if bottom_wick > top_wick else Direction.DOWN
    
    # See if it interacted with a pivot
    pivot_match = None
    if pivots:
        for pivot in reversed(pivots):
            if pivot.timestamp >= current_bar.timestamp:
                continue
                
            if direction == Direction.UP:
                # Bounced off support
                if pivot.direction == Direction.DOWN and current_bar.low <= pivot.price + (1.0 * atr):
                    pivot_match = pivot
                    break
            else:
                # Rejected off resistance
                if pivot.direction == Direction.UP and current_bar.high >= pivot.price - (1.0 * atr):
                    pivot_match = pivot
                    break
                    
    stop_price = current_bar.low - (MIN_STOP_ATR_MULT * atr) if direction == Direction.UP else current_bar.high + (MIN_STOP_ATR_MULT * atr)
    
    cand = SetupCandidate(
        asset=current_bar.asset,
        timeframe=current_bar.timeframe,
        setup_type=SetupType.LIQUIDATION_FLUSH,
        setup_class=SetupClass.REVERSAL,
        direction=direction,
        trigger_pivot=pivot_match,
        detected_at=current_bar.timestamp,
        detected_bar_index=len(bars)-1,
        trigger_price=current_bar.close,
        stop_price=stop_price
    )
    candidates.append(cand)
    
    return candidates
