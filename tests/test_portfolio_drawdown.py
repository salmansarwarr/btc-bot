import pytest
from bot.structs import PortfolioState, DrawdownTier, SetupCandidate, Direction
from bot.portfolio.drawdown import check_drawdown_tier
from bot.entry_risk.sizer import compute_position_size
from bot.config import (
    DRAWDOWN_TIER_1_PCT,
    DRAWDOWN_TIER_2_PCT,
    DRAWDOWN_TIER_3_PCT,
    DRAWDOWN_RECOVERY_HYSTERESIS,
    DRAWDOWN_TIER_1_RISK_MULT,
    HEAT_COOLOFF_LOSS_STREAK,
    RISK_PCT_BY_CONVICTION
)

def test_drawdown_tier_downgrades():
    portfolio = PortfolioState(equity=100000.0, equity_ath=100000.0)
    
    # 1. Drop to 9% DD (Safe, Tier 0)
    portfolio.equity = 91000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_0
    
    # 2. Drop to 10% DD (Tier 1 threshold)
    portfolio.equity = 90000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    
    # 3. Drop to 20% DD (Tier 2 threshold)
    portfolio.equity = 80000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_2
    
    # 4. Drop to 30% DD (Tier 3 threshold)
    portfolio.equity = 70000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_3

def test_drawdown_recovery_hysteresis():
    portfolio = PortfolioState(equity=80000.0, equity_ath=100000.0, drawdown_tier=DrawdownTier.TIER_2)
    
    # Recovery from TIER_2 -> TIER_1 requires DD <= TIER_2_PCT * HYSTERESIS
    # 20% * 0.5 = 10%. Equity must reach 90000.
    
    # At 89000 (11% DD), we are still TIER_2
    portfolio.equity = 89000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_2
    
    # At 90000 (10% DD), we recover to TIER_1
    portfolio.equity = 90000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    
    # Recovery from TIER_1 -> TIER_0 requires DD <= TIER_1_PCT * HYSTERESIS
    # 10% * 0.5 = 5%. Equity must reach 95000.
    
    # At 94000 (6% DD), still TIER_1
    portfolio.equity = 94000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    
    # At 95000 (5% DD), we recover to TIER_0
    portfolio.equity = 95000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_0

def test_tier1_reduces_risk_per_trade():
    cand = SetupCandidate(
        asset="BTC",
        direction=Direction.UP,
        trigger_price=100.0,
        stop_price=90.0,
        conviction_score=2 # AGGRESSIVE, RISK_PCT = 0.02
    )
    
    account_equity = 100000.0
    risk_dist = 10.0
    
    # Tier 0 (normal): Risk = 2% of 100k = $2000 / 10 = 200 units
    size_t0 = compute_position_size(cand, account_equity, DrawdownTier.TIER_0)
    assert size_t0 == 200.0
    
    # Tier 1 (halved risk): Risk = 2% * 0.5 = 1% of 100k = $1000 / 10 = 100 units
    size_t1 = compute_position_size(cand, account_equity, DrawdownTier.TIER_1)
    assert size_t1 == 100.0
    
    # Tier 2 (halt): Risk = 0
    size_t2 = compute_position_size(cand, account_equity, DrawdownTier.TIER_2)
    assert size_t2 == 0.0

def test_consecutive_losses_forces_tier1():
    portfolio = PortfolioState(equity=99000.0, equity_ath=100000.0) # 1% DD
    
    portfolio.consecutive_losses = HEAT_COOLOFF_LOSS_STREAK
    check_drawdown_tier(portfolio)
    
    # Despite only 1% DD, forced into TIER_1
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    
    # Even if equity recovers to ATH, cannot drop to TIER_0 while loss streak is active
    portfolio.equity = 100000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    
    # Once losses reset, recovers to TIER_0 immediately because DD is 0%
    portfolio.consecutive_losses = 0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_0
