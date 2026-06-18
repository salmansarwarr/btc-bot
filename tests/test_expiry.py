import pytest
from datetime import datetime, timezone
from bot.structs import TradeState, SetupClass, Direction
from bot.config import (
    EXPIRY_TRAP_BARS,
    EXPIRY_TRAP_ATR_MULT,
    EXPIRY_CONTINUATION_BARS,
    EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT,
    EXPIRY_HTF_BASE_BARS,
    EXPIRY_HTF_MULTIPLIER,
    APPROACHING_TARGET_THRESHOLD,
)
from bot.trade_management.expiry import check_time_expiry, approaching_target

def test_expiry_trap_closes():
    trade = TradeState(
        id="E1",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.TRAP,
        entry_price=100.0,
        position_size=10.0,
        bars_in_trade=EXPIRY_TRAP_BARS,
    )
    atr = 10.0
    # EXPIRY_TRAP_ATR_MULT is typically 0.5. Needs to move < 5.0 to close.
    price_stalled = 104.0
    
    check_time_expiry(trade, price_stalled, 0, atr)
    assert trade.is_open == False
    assert trade.position_size == 0.0

def test_expiry_trap_holds():
    trade = TradeState(
        id="E2",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.TRAP,
        entry_price=100.0,
        position_size=10.0,
        bars_in_trade=EXPIRY_TRAP_BARS,
    )
    atr = 10.0
    price_moved = 111.0 # >= 10.0
    
    check_time_expiry(trade, price_moved, 0, atr)
    assert trade.is_open == True

def test_expiry_continuation_tightens_then_closes():
    trade = TradeState(
        id="E3",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.CONTINUATION,
        entry_price=100.0,
        stop_price=90.0,
        position_size=10.0,
        bars_in_trade=EXPIRY_CONTINUATION_BARS,
    )
    atr = 10.0
    price_stalled = 104.0
    
    # 1. Bar reaches EXPIRY_CONTINUATION_BARS and is stalling -> tightens stop
    check_time_expiry(trade, price_stalled, 0, atr)
    
    assert trade.is_open == True
    assert trade.expiry_tightened == True
    # Stop becomes entry - offset = 100 - (0.1 * 10) = 99.0
    assert trade.stop_price == 99.0
    
    # 2. Subsequent bar and still stalling -> closes trade
    trade.bars_in_trade += 1
    check_time_expiry(trade, price_stalled, 0, atr)
    
    assert trade.is_open == False
    assert trade.position_size == 0.0

def test_expiry_htf_swing_closes_if_not_approaching_target():
    trade = TradeState(
        id="E4",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.HTF_SWING,
        entry_price=100.0,
        targets=[120.0, 150.0],
        current_target_index=0,
        position_size=10.0,
        bars_in_trade=EXPIRY_HTF_BASE_BARS * EXPIRY_HTF_MULTIPLIER,
    )
    atr = 10.0
    # Target is 150. Total dist = 50. 60% = 30. So needs to be >= 130 to be approaching target.
    price_stalled = 120.0 # 20 / 50 = 40% < 60%
    
    assert not approaching_target(trade, price_stalled)
    
    check_time_expiry(trade, price_stalled, 0, atr)
    assert trade.is_open == False

def test_expiry_htf_swing_holds_if_approaching_target():
    trade = TradeState(
        id="E5",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.HTF_SWING,
        entry_price=100.0,
        targets=[120.0, 150.0],
        current_target_index=0,
        position_size=10.0,
        bars_in_trade=EXPIRY_HTF_BASE_BARS * EXPIRY_HTF_MULTIPLIER,
    )
    atr = 10.0
    # Needs to be >= 130
    price_approaching = 131.0
    
    assert approaching_target(trade, price_approaching)
    
    check_time_expiry(trade, price_approaching, 0, atr)
    assert trade.is_open == True
