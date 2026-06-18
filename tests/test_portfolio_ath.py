import pytest
from datetime import datetime, timezone, timedelta
from bot.structs import PortfolioState
from bot.portfolio.ath_realization import check_ath_realization
from bot.config import (
    ATH_GAIN_PCT_30D,
    ATH_REALIZATION_PCT,
    ATH_BACKSTOP_DAYS,
    ATH_BACKSTOP_PCT,
    ATH_BACKSTOP_PROXIMITY_PCT
)

def test_primary_realization_triggers_at_30_pct_gain():
    portfolio = PortfolioState(equity=130000.0, equity_ath=100000.0)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    portfolio.last_realization_date = now - timedelta(days=5) # not backstop time
    
    equity_30d_ago = 100000.0
    # Gain = (130k - 100k) / 100k = 30%. Trigger!
    check_ath_realization(portfolio, equity_30d_ago, now)
    
    expected_realization = 130000.0 * ATH_REALIZATION_PCT # 13,000
    assert portfolio.fund_balances["capitulation_reserve"] == expected_realization
    assert portfolio.equity == 130000.0 - expected_realization
    assert portfolio.equity_ath == portfolio.equity # ATH drops
    assert portfolio.last_realization_date == now

def test_primary_realization_does_not_trigger_below_threshold():
    portfolio = PortfolioState(equity=129000.0, equity_ath=100000.0)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    portfolio.last_realization_date = now - timedelta(days=5)
    
    equity_30d_ago = 100000.0
    # Gain = 29%
    check_ath_realization(portfolio, equity_30d_ago, now)
    
    assert portfolio.fund_balances.get("capitulation_reserve", 0.0) == 0.0
    assert portfolio.equity == 129000.0
    assert portfolio.equity_ath == 129000.0 # newly set ATH

def test_backstop_fires_when_conditions_met():
    portfolio = PortfolioState(equity=100000.0, equity_ath=100000.0)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Days since last >= ATH_BACKSTOP_DAYS (e.g. 90)
    portfolio.last_realization_date = now - timedelta(days=ATH_BACKSTOP_DAYS + 1)
    
    equity_30d_ago = 100000.0 # Gain = 0%, no primary trigger
    
    # Proximity threshold: 100k * (1 - 0.01) = 99k. Equity is 100k. Should fire!
    check_ath_realization(portfolio, equity_30d_ago, now)
    
    expected_realization = 100000.0 * ATH_BACKSTOP_PCT
    assert portfolio.fund_balances["capitulation_reserve"] == expected_realization
    assert portfolio.equity == 100000.0 - expected_realization
    assert portfolio.last_realization_date == now

def test_backstop_does_not_fire_if_not_enough_days():
    portfolio = PortfolioState(equity=100000.0, equity_ath=100000.0)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Days since last < ATH_BACKSTOP_DAYS
    portfolio.last_realization_date = now - timedelta(days=ATH_BACKSTOP_DAYS - 1)
    
    equity_30d_ago = 100000.0
    
    check_ath_realization(portfolio, equity_30d_ago, now)
    
    assert portfolio.fund_balances.get("capitulation_reserve", 0.0) == 0.0

def test_backstop_does_not_fire_if_not_in_proximity():
    portfolio = PortfolioState(equity=98000.0, equity_ath=100000.0)
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    # Days since last >= ATH_BACKSTOP_DAYS
    portfolio.last_realization_date = now - timedelta(days=ATH_BACKSTOP_DAYS + 1)
    
    equity_30d_ago = 98000.0
    
    # Proximity threshold: 100k * (1 - 0.01) = 99k. Equity is 98k. Should NOT fire!
    check_ath_realization(portfolio, equity_30d_ago, now)
    
    assert portfolio.fund_balances.get("capitulation_reserve", 0.0) == 0.0
