import pytest
from datetime import datetime, timezone
from bot.structs import TradeState, SetupClass, Direction
from bot.config import STALL_BARS, STALL_ATR_MULT
from bot.trade_management.stalling import check_stalling

def test_stalling_proxy_a_triggers_after_n_bars():
    trade = TradeState(
        id="S1",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.CONTINUATION,
        entry_price=100.0,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    now = datetime.now(timezone.utc)
    
    # Needs to be within STALL_ATR_MULT * atr
    # STALL_ATR_MULT is usually 0.1. Dist <= 1.0
    price_stall = 100.5
    
    for i in range(STALL_BARS - 1):
        check_stalling(trade, price_stall, atr, now)
        assert trade.stall_band_counter == i + 1
        assert trade.stalling_flag == False
        
    # On the Nth bar, it should trigger
    check_stalling(trade, price_stall, atr, now)
    assert trade.stall_band_counter == STALL_BARS
    assert trade.stalling_flag == True
    assert trade.position_size == 5.0  # Reduced by 50%
    assert len(trade.partials_taken) == 1

def test_stalling_proxy_a_resets_counter():
    trade = TradeState(
        id="S2",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.CONTINUATION,
        entry_price=100.0,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    now = datetime.now(timezone.utc)
    
    price_stall = 100.5
    price_away = 106.0  # > 1.0 distance
    
    check_stalling(trade, price_stall, atr, now)
    assert trade.stall_band_counter == 1
    
    check_stalling(trade, price_away, atr, now)
    assert trade.stall_band_counter == 0
