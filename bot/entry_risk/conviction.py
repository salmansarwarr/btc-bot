import math
from typing import List, Optional

from bot.structs import (
    SetupCandidate, BiasState, Direction, OHLCV_Bar, PivotStrength,
    ManagementMode, SetupType
)
from bot.config import (
    PIVOT_PERCENTILE_SCORING_ENABLED, PIVOT_PERCENTILE_LOOKBACK,
    PIVOT_MAJOR_PERCENTILE, MINOR_PIVOT_RESPECTED_BONUS,
    DEEP_PULLBACK_CONFLUENCE_BONUS, CONVICTION_DIRECT_ENTRY_THRESHOLD
)

def compute_conviction_score(
    candidate: SetupCandidate,
    htf_bias: BiasState,
    bars_for_percentile: Optional[List[OHLCV_Bar]] = None
) -> None:
    """
    Computes the conviction score for a SetupCandidate and sets its 
    conviction_score and management_mode in-place.
    
    Equal-weight 3-point score:
    Base: +1 point for a valid setup.
    Filter: +1 point if HTF Bias aligns.
    Confluence: Up to +1 point from quality metrics (percentile, divergences, etc).
    """
    score = 1.0  # Base point
    
    # 1. HTF Bias Alignment
    if htf_bias == BiasState.BULLISH and candidate.direction == Direction.UP:
        score += 1.0
    elif htf_bias == BiasState.BEARISH and candidate.direction == Direction.DOWN:
        score += 1.0
        
    # 2. Confluence / Quality
    confluence_score = 0.0
    
    if candidate.setup_type == SetupType.MOMENTUM_DIVERGENCE:
        # RSI Divergence implies extreme-zone (already filtered in detection)
        confluence_score += 1.0
        
    if candidate.trigger_pivot is not None:
        if candidate.trigger_pivot.strength == PivotStrength.MAJOR:
            if PIVOT_PERCENTILE_SCORING_ENABLED and bars_for_percentile:
                # Percentile check
                lookback = PIVOT_PERCENTILE_LOOKBACK
                window = bars_for_percentile[-lookback:]
                if window:
                    highs = [b.high for b in window]
                    lows = [b.low for b in window]
                    highest = max(highs)
                    lowest = min(lows)
                    range_size = highest - lowest
                    
                    if range_size > 0:
                        if candidate.trigger_pivot.direction == Direction.UP:
                            # Resistance pivot must be in top X%
                            threshold = highest - (range_size * PIVOT_MAJOR_PERCENTILE)
                            if candidate.trigger_pivot.price >= threshold:
                                confluence_score += 1.0
                        else:
                            # Support pivot must be in bottom X%
                            threshold = lowest + (range_size * PIVOT_MAJOR_PERCENTILE)
                            if candidate.trigger_pivot.price <= threshold:
                                confluence_score += 1.0
            else:
                confluence_score += 1.0
        elif candidate.trigger_pivot.strength == PivotStrength.MINOR:
            if candidate.trigger_pivot.first_reaction_confirmed:
                confluence_score += MINOR_PIVOT_RESPECTED_BONUS
                
    if candidate.deep_pullback_consolidation_confluence:
        confluence_score += DEEP_PULLBACK_CONFLUENCE_BONUS
        
    # Cap confluence contribution at 1.0
    score += min(1.0, confluence_score)
    
    # Round to nearest integer (int(x + 0.5) avoids banker's rounding issues with 1.5/2.5)
    final_score = int(score + 0.5)
    
    # Clamp between 0 and 3 just in case
    final_score = min(3, max(0, final_score))
    
    candidate.conviction_score = final_score
    
    if final_score >= 3:
        candidate.management_mode = ManagementMode.CONSERVATIVE
    else:
        candidate.management_mode = ManagementMode.AGGRESSIVE
