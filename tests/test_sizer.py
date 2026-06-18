import pytest
from bot.structs import SetupCandidate
from bot.entry_risk.sizer import compute_position_size
from bot.config import RISK_PCT_BY_CONVICTION

def test_compute_position_size_level_3():
    # Equity = 10,000
    # Score 3 risk_pct = 0.03 (3%) -> $300 at risk
    # Entry = 100, Stop = 90 -> Distance = 10
    # Position size = 300 / 10 = 30 units
    cand = SetupCandidate(
        trigger_price=100.0,
        stop_price=90.0,
        conviction_score=3
    )
    
    equity = 10000.0
    size = compute_position_size(cand, equity)
    
    expected_risk = equity * RISK_PCT_BY_CONVICTION[3]
    expected_distance = 10.0
    assert size == expected_risk / expected_distance
    assert size == 30.0

def test_compute_position_size_level_2():
    # Equity = 10,000
    # Score 2 risk_pct = 0.02 (2%) -> $200 at risk
    # Entry = 50, Stop = 60 -> Distance = 10
    # Position size = 200 / 10 = 20 units
    cand = SetupCandidate(
        trigger_price=50.0,
        stop_price=60.0,
        conviction_score=2
    )
    
    equity = 10000.0
    size = compute_position_size(cand, equity)
    assert size == 20.0

def test_compute_position_size_level_1():
    # Equity = 10,000
    # Score 1 risk_pct = 0.01 (1%) -> $100 at risk
    # Entry = 200, Stop = 150 -> Distance = 50
    # Position size = 100 / 50 = 2 units
    cand = SetupCandidate(
        trigger_price=200.0,
        stop_price=150.0,
        conviction_score=1
    )
    
    equity = 10000.0
    size = compute_position_size(cand, equity)
    assert size == 2.0

def test_compute_position_size_level_0():
    # Score 0 -> Risk = 0% -> Size = 0
    cand = SetupCandidate(
        trigger_price=100.0,
        stop_price=90.0,
        conviction_score=0
    )
    
    size = compute_position_size(cand, 10000.0)
    assert size == 0.0

def test_compute_position_size_tight_stop_edge_case():
    # Entry = 100.0, Stop = 100.0 -> Distance = 0
    # Should safely return 0.0 to prevent ZeroDivisionError
    cand = SetupCandidate(
        trigger_price=100.0,
        stop_price=100.0,
        conviction_score=3
    )
    size = compute_position_size(cand, 10000.0)
    assert size == 0.0

def test_compute_position_size_negative_equity():
    cand = SetupCandidate(
        trigger_price=100.0,
        stop_price=90.0,
        conviction_score=3
    )
    size = compute_position_size(cand, -5000.0)
    assert size == 0.0

def test_compute_position_size_invalid_prices():
    cand = SetupCandidate(
        trigger_price=-100.0,
        stop_price=90.0,
        conviction_score=3
    )
    size = compute_position_size(cand, 10000.0)
    assert size == 0.0
