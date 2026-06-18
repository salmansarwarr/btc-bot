from typing import List
from datetime import timedelta

from bot.structs import (
    OHLCV_Bar, PivotFlag, SetupCandidate, AssetConfig, ExternalFeedState,
    MarketBasket, TrendClass, Direction
)

from bot.setup_detection.sfp import detect_sfp
from bot.setup_detection.cdc import detect_cdc
from bot.setup_detection.msb_pullback import detect_msb_pullback
from bot.setup_detection.open_drive import detect_open_drive
from bot.setup_detection.sr_flip import detect_sr_flip
from bot.setup_detection.consolidation import detect_consolidation
from bot.setup_detection.momentum_divergence import detect_momentum_divergence
from bot.setup_detection.liquidation_flush import detect_liquidation_flush

def passes_relative_strength_filter(
    bars: List[OHLCV_Bar],
    market_basket: MarketBasket,
    trend_class: TrendClass,
    direction: Direction
) -> bool:
    """
    Spec I-8: Applied only for LOCKOUT_TREND + UP direction candidates.
    If the market is red (btc_eth_avg_24h_change < 0) and the asset is 
    underperforming the average, the setup is vetoed.
    Passes through on a green market day regardless.
    """
    if trend_class != TrendClass.LOCKOUT_TREND or direction != Direction.UP:
        return True
        
    if market_basket.btc_eth_avg_24h_change >= 0:
        return True
        
    if not bars:
        return True
        
    current_bar = bars[-1]
    
    # We need to find the bar 24 hours ago
    target_time = current_bar.timestamp - timedelta(hours=24)
    bar_24h_ago = None
    
    for b in reversed(bars):
        if b.timestamp <= target_time:
            bar_24h_ago = b
            break
            
    if not bar_24h_ago:
        return True
        
    asset_change = (current_bar.close - bar_24h_ago.close) / bar_24h_ago.close
    
    # Veto if asset underperforms the average on a red day
    if asset_change < market_basket.btc_eth_avg_24h_change:
        return False
        
    return True


def run_setup_detection(
    bars: List[OHLCV_Bar],
    pivots: List[PivotFlag],
    atr: float,
    config: AssetConfig,
    feed: ExternalFeedState,
    market_basket: MarketBasket,
    trend_class: TrendClass
) -> List[SetupCandidate]:
    """
    Orchestrate all detector functions for one (asset, timeframe) bar close.
    Aggregates candidates and applies the relative strength filter.
    """
    candidates: List[SetupCandidate] = []
    
    # 1. Trending Context
    candidates.extend(detect_sfp(bars, pivots, atr))
    candidates.extend(detect_cdc(bars, pivots, atr, include_pattern_failure=False))
    candidates.extend(detect_msb_pullback(bars, pivots, atr))
    candidates.extend(detect_open_drive(bars, pivots, atr))
    candidates.extend(detect_sr_flip(bars, pivots, atr))
    
    # 2. Range Context
    candidates.extend(detect_consolidation(bars, atr))
    
    # 3. Macro / Divergence
    candidates.extend(detect_momentum_divergence(bars, atr))
    candidates.extend(detect_liquidation_flush(bars, pivots, atr, config, feed))
    
    # Apply Relative Strength Filter
    filtered_candidates = []
    for cand in candidates:
        if passes_relative_strength_filter(bars, market_basket, trend_class, cand.direction):
            filtered_candidates.append(cand)
                     
    return filtered_candidates
