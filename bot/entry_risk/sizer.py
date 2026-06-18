from bot.structs import SetupCandidate, DrawdownTier
from bot.config import RISK_PCT_BY_CONVICTION, DRAWDOWN_TIER_1_RISK_MULT

def compute_position_size(
    candidate: SetupCandidate,
    account_equity: float,
    drawdown_tier: DrawdownTier = DrawdownTier.TIER_0
) -> float:
    """
    Computes position size (in base asset units) using conviction-based risk %.
    
    Formula:
      Position Size = (Account Equity × Risk Pct × Tier Mult) / |Entry Price - Stop Price|
      
    Returns 0.0 if conviction is 0, stop distance is 0, or equity <= 0.
    """
    if account_equity <= 0:
        return 0.0
        
    if drawdown_tier == DrawdownTier.TIER_2 or drawdown_tier == DrawdownTier.TIER_3:
        return 0.0  # Trading is completely halted

        
    # Get the risk percentage based on the conviction score
    conviction = candidate.conviction_score
    risk_pct = RISK_PCT_BY_CONVICTION.get(conviction, 0.0)
    
    if risk_pct <= 0.0:
        return 0.0
        
    entry_price = candidate.trigger_price
    stop_price = candidate.stop_price
    
    if entry_price <= 0 or stop_price <= 0:
        return 0.0
        
    risk_distance = abs(entry_price - stop_price)
    
    # Edge case: prevent division by zero for impossibly tight stops
    if risk_distance == 0.0:
        return 0.0
        
    if drawdown_tier == DrawdownTier.TIER_1:
        risk_pct *= DRAWDOWN_TIER_1_RISK_MULT
        
    capital_at_risk = account_equity * risk_pct
    position_size = capital_at_risk / risk_distance
    
    return position_size
