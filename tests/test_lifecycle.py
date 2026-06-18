import pytest
from datetime import datetime, timezone
from bot.structs import TradeState, Direction, SetupClass, ManagementMode
from bot.config import STALL_BARS, EXPIRY_TRAP_BARS
from bot.trade_management.lifecycle import update_trade

def test_lifecycle_stall_to_expiry():
    # Setup a TRAP trade that stalls and then expires
    trade = TradeState(
        id="L1",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.TRAP,
        management_mode=ManagementMode.CONSERVATIVE,
        entry_price=100.0,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    # Price stays right at entry (stalling)
    price = 100.0
    now = datetime.now(timezone.utc)
    
    # Run through bars up to STALL_BARS (e.g. 3 bars)
    for i in range(STALL_BARS - 1):
        events = update_trade(trade, price, 0, atr, now)
        assert len(events) == 1
        assert events[0]["action"] == "HOLD"
        
    # At STALL_BARS, Proxy A stall triggers (cuts position 50%)
    events = update_trade(trade, price, 0, atr, now)
    assert any(e["action"] == "PARTIAL" and e["reason"] == "stalling_cut" for e in events)
    assert trade.position_size == 5.0
    
    # Keep going until trade.bars_in_trade reaches EXPIRY_TRAP_BARS
    while trade.bars_in_trade < EXPIRY_TRAP_BARS:
        events = update_trade(trade, price, 0, atr, now)
        assert events[0]["action"] == "HOLD"
        
    # Now that it has been in the trade for EXPIRY_TRAP_BARS, the next evaluation will expire it
    events = update_trade(trade, price, 0, atr, now)
    assert any(e["action"] == "CLOSE" and e["reason"] == "time_expiry" for e in events)
    assert trade.is_open == False
    assert trade.position_size == 0.0


def test_lifecycle_fta_reject_close():
    # Setup an AGGRESSIVE trade that gets rejected at FTA
    trade = TradeState(
        id="L2",
        is_open=True,
        direction=Direction.DOWN,
        setup_class=SetupClass.CONTINUATION,
        management_mode=ManagementMode.AGGRESSIVE,
        entry_price=100.0,
        stop_price=110.0,
        targets=[90.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    # Reject is reaching 90 but not crossing by offset (1.5). E.g. 89.0
    price_reject = 89.0
    now = datetime.now(timezone.utc)
    
    events = update_trade(trade, price_reject, 0, atr, now)
    
    assert any(e["action"] == "CLOSE" and e["reason"] == "fta_rejection" for e in events)
    assert trade.is_open == False


def test_lifecycle_fta_break_compound():
    # Setup an AGGRESSIVE trade that breaks FTA cleanly
    trade = TradeState(
        id="L3",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.CONTINUATION,
        management_mode=ManagementMode.AGGRESSIVE,
        entry_price=100.0,
        stop_price=90.0,
        targets=[110.0, 120.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
        partials_scheduled=[0.33, 0.33, 0.34]
    )
    atr = 10.0
    # Clean break is crossing by offset (1.5). E.g. 112.0
    price_break = 112.0
    now = datetime.now(timezone.utc)
    
    events = update_trade(trade, price_break, 0, atr, now)
    
    assert any(e["action"] == "COMPOUND" and e["reason"] == "fta_break" for e in events)
    assert trade.is_open == True
    # Position compounds from 10.0 to 15.0
    assert trade.position_size == 15.0
    # The scheduled partial for the FTA was skipped, so only 2 remain
    assert len(trade.partials_scheduled) == 2


def test_lifecycle_dynamic_r_tighten():
    trade = TradeState(
        id="L4",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.HTF_SWING,
        management_mode=ManagementMode.CONSERVATIVE,
        entry_price=100.0,
        stop_price=90.0,
        initial_risk_usd=100.0,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    price_2r = 120.0
    now = datetime.now(timezone.utc)
    
    events = update_trade(trade, price_2r, 0, atr, now)
    
    assert any(e["action"] == "TIGHTEN" and e["reason"] == "dynamic_r_lock" for e in events)
    assert trade.stop_price == 110.0
