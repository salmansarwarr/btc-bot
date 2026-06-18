import pytest
from bot.structs import PortfolioState, SetupCandidate, TradeState, Direction
from bot.config import MAX_HEAT_PCT, MAX_CORRELATED_HEAT_PCT, HEAT_COOLOFF_LOSS_STREAK, HEAT_COOLOFF_REDUCTION
from bot.portfolio.heat import enforce_portfolio_heat, update_heat_cooloff

def test_heat_ceiling_blocks_new_trades():
    portfolio = PortfolioState(equity=100000.0)
    # Give it an open trade taking up 5% risk
    t1 = TradeState(id="T1", asset="ETH", initial_risk_usd=5000.0, position_size=1)
    portfolio.open_trades["T1"] = t1
    
    # Candidate needs 2% risk. Total = 7% > MAX_HEAT_PCT (6%)
    cand = TradeState(asset="XRP", direction=Direction.UP, entry_price=10.0, stop_price=9.0, initial_risk_usd=2000.0)
    
    # Should block
    assert enforce_portfolio_heat(portfolio, cand) == True
    
    # But a smaller candidate of 0.5% should pass
    cand2 = TradeState(asset="XRP", direction=Direction.UP, entry_price=10.0, stop_price=9.0, initial_risk_usd=500.0)
    assert enforce_portfolio_heat(portfolio, cand2) == False

def test_three_consecutive_losses_reduce_effective_max_heat():
    portfolio = PortfolioState(equity=100000.0)
    
    # Initially 6%
    update_heat_cooloff(portfolio, trade_closed_as_loss=True)
    assert portfolio.consecutive_losses == 1
    assert portfolio.effective_max_heat == MAX_HEAT_PCT
    
    update_heat_cooloff(portfolio, trade_closed_as_loss=True)
    assert portfolio.consecutive_losses == 2
    assert portfolio.effective_max_heat == MAX_HEAT_PCT
    
    # 3rd loss triggers cooloff
    update_heat_cooloff(portfolio, trade_closed_as_loss=True)
    assert portfolio.consecutive_losses == 3
    expected_heat = MAX_HEAT_PCT * (1.0 - HEAT_COOLOFF_REDUCTION)
    assert portfolio.effective_max_heat == expected_heat
    
    # With effective max heat reduced (e.g. 4.5%), a 5% trade should now be blocked
    t1 = TradeState(id="T1", asset="ETH", initial_risk_usd=3000.0, position_size=1)
    portfolio.open_trades["T1"] = t1
    cand = TradeState(asset="XRP", direction=Direction.UP, entry_price=10.0, stop_price=9.0, initial_risk_usd=2000.0)
    
    # Total risk = 5%. 5% > 4.5% (effective), so it blocks!
    assert enforce_portfolio_heat(portfolio, cand) == True

def test_correlated_bucket_checked_independently():
    portfolio = PortfolioState(equity=100000.0)
    
    # Let's say MAX_HEAT_PCT = 0.06, MAX_CORRELATED_HEAT_PCT = 0.08 (from config)
    # This means a bucket can't exceed 8%. But since total heat is 6%, total heat will trigger first usually.
    # Let's artificially set effective_max_heat to 10% to test bucket independently
    portfolio.effective_max_heat = 0.10
    
    # 5% in BTC
    t1 = TradeState(id="T1", asset="BTC", initial_risk_usd=5000.0, position_size=1)
    portfolio.open_trades["T1"] = t1
    
    # Candidate for ETH needs 4%. BTC and ETH are in "BTC_CORE" bucket.
    # Total bucket risk = 5% + 4% = 9% > 8%.
    cand = TradeState(asset="ETH", direction=Direction.UP, entry_price=10.0, stop_price=9.0, initial_risk_usd=4000.0)
    
    assert enforce_portfolio_heat(portfolio, cand) == True
    
    # But if Candidate is UNI (bucket "DEFI"), it only adds 4% to DEFI bucket.
    # DEFI bucket = 4% <= 8%. Total heat = 9% <= 10%. So it passes!
    cand_defi = TradeState(asset="UNI", direction=Direction.UP, entry_price=10.0, stop_price=9.0, initial_risk_usd=4000.0)
    assert enforce_portfolio_heat(portfolio, cand_defi) == False

def test_heat_recovers_after_win():
    portfolio = PortfolioState(equity=100000.0)
    portfolio.consecutive_losses = HEAT_COOLOFF_LOSS_STREAK
    portfolio.effective_max_heat = MAX_HEAT_PCT * (1.0 - HEAT_COOLOFF_REDUCTION)
    
    # A winning trade comes in!
    update_heat_cooloff(portfolio, trade_closed_as_loss=False)
    
    # Losses reset, heat recovers
    assert portfolio.consecutive_losses == 0
    assert portfolio.effective_max_heat == MAX_HEAT_PCT
