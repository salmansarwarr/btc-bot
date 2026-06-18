import pytest
from bot.structs import TradeState, Direction
from bot.trade_management.dynamic_r import check_dynamic_r

def test_dynamic_r_up_trade_locks_at_2r():
    trade = TradeState(
        id="D1",
        is_open=True,
        direction=Direction.UP,
        entry_price=100.0,
        stop_price=90.0,
        initial_position_size=10.0,
        initial_risk_usd=100.0, # R = 10.0 per unit. (entry - stop) * size = (10) * 10 = 100
    )
    atr = 10.0
    
    # At 1.5R (price = 115) -> shouldn't lock
    check_dynamic_r(trade, 115.0, atr)
    assert trade.stop_price == 90.0
    
    # At 2R (price = 120) -> should lock 1R below (120 - 10 = 110)
    check_dynamic_r(trade, 120.0, atr)
    assert trade.stop_price == 110.0
    
    # At 3R (price = 130) -> should trail (130 - 10 = 120)
    check_dynamic_r(trade, 130.0, atr)
    assert trade.stop_price == 120.0
    
    # Drops back to 2.5R (price = 125) -> stop should NOT move backwards
    check_dynamic_r(trade, 125.0, atr)
    assert trade.stop_price == 120.0

def test_dynamic_r_down_trade_locks_at_2r():
    trade = TradeState(
        id="D2",
        is_open=True,
        direction=Direction.DOWN,
        entry_price=100.0,
        stop_price=110.0,
        initial_position_size=10.0,
        initial_risk_usd=100.0, # R = 10.0
    )
    atr = 10.0
    
    # At 2R (price = 80) -> should lock 1R above (80 + 10 = 90)
    check_dynamic_r(trade, 80.0, atr)
    assert trade.stop_price == 90.0
    
    # At 4R (price = 60) -> trail to (60 + 10 = 70)
    check_dynamic_r(trade, 60.0, atr)
    assert trade.stop_price == 70.0
    
    # Goes back to 3R (price = 70) -> stop should NOT move back up
    check_dynamic_r(trade, 70.0, atr)
    assert trade.stop_price == 70.0
