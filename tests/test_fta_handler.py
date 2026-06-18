import pytest
from datetime import datetime, timezone
from bot.structs import TradeState, Direction, ManagementMode
from bot.config import BREAK_CLOSE_BEYOND_ATR_MULT
from bot.trade_management.fta_handler import check_fta_interaction
from bot.trade_management.actions import compound_position

# For testing, we mock or inspect TradeState mutations since the helpers mutate TradeState.

def test_fta_aggressive_break():
    # AGGRESSIVE + Break -> compound
    trade = TradeState(
        id="T1",
        is_open=True,
        direction=Direction.UP,
        management_mode=ManagementMode.AGGRESSIVE,
        targets=[100.0, 150.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
        partials_scheduled=[0.33, 0.33, 0.34],
    )
    atr = 10.0
    # Clean break condition: current_price >= target + (BREAK_CLOSE_BEYOND_ATR_MULT * atr)
    # BREAK_CLOSE_BEYOND_ATR_MULT is usually 0.15. 100 + 1.5 = 101.5
    price_break = 100.0 + (BREAK_CLOSE_BEYOND_ATR_MULT * atr) + 0.1
    
    check_fta_interaction(trade, price_break, atr)
    
    assert trade.is_open == True
    # Aggressive break -> compound_position -> position size increases
    assert trade.position_size == 15.0  # 10.0 * 1.5
    # Scheduled partial for THIS fta is skipped (popped)
    assert len(trade.partials_scheduled) == 2
    assert trade.current_target_index == 1

def test_fta_aggressive_reject():
    # AGGRESSIVE + Reject -> close trade
    trade = TradeState(
        id="T2",
        is_open=True,
        direction=Direction.DOWN,
        management_mode=ManagementMode.AGGRESSIVE,
        targets=[100.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
        partials_scheduled=[0.33, 0.33, 0.34],
    )
    atr = 10.0
    # Target = 100. Reject for DOWN means current_price <= target but NOT <= target - offset
    # offset = 1.5. So reject range is [98.5, 100.0]. Let's pick 99.0.
    price_reject = 99.0
    
    check_fta_interaction(trade, price_reject, atr)
    
    # Aggressive reject -> close trade
    assert trade.is_open == False
    assert trade.position_size == 0.0
    assert trade.current_target_index == 1

def test_fta_conservative_break():
    # CONSERVATIVE + Break -> skip partial, hold
    trade = TradeState(
        id="T3",
        is_open=True,
        direction=Direction.UP,
        management_mode=ManagementMode.CONSERVATIVE,
        targets=[100.0, 150.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
        partials_scheduled=[0.33, 0.33, 0.34],
    )
    atr = 10.0
    price_break = 100.0 + (BREAK_CLOSE_BEYOND_ATR_MULT * atr) + 0.1
    
    check_fta_interaction(trade, price_break, atr)
    
    assert trade.is_open == True
    # Conservative break -> does NOT compound
    assert trade.position_size == 10.0
    # Scheduled partial for THIS fta is skipped
    assert len(trade.partials_scheduled) == 2
    assert trade.current_target_index == 1

def test_fta_conservative_reject():
    # CONSERVATIVE + Reject -> take scheduled partial
    trade = TradeState(
        id="T4",
        is_open=True,
        direction=Direction.DOWN,
        management_mode=ManagementMode.CONSERVATIVE,
        targets=[100.0],
        current_target_index=0,
        position_size=10.0,
        initial_position_size=10.0,
        partials_scheduled=[0.33, 0.33, 0.34],
    )
    atr = 10.0
    price_reject = 99.0
    
    check_fta_interaction(trade, price_reject, atr)
    
    assert trade.is_open == True
    # Takes scheduled partial of 0.33 -> 3.3 reduced -> remaining 6.7
    assert trade.position_size == pytest.approx(6.7)
    assert len(trade.partials_scheduled) == 2
    assert trade.current_target_index == 1
    assert len(trade.partials_taken) == 1
    assert trade.partials_taken[0].fraction == 0.33

def test_trap_moved_away_and_reentry():
    from bot.trade_management.stalling import check_stalling
    from bot.structs import SetupClass, PivotFlag, PivotStrength
    
    pivot = PivotFlag("BTC", "H1", 100.0, Direction.DOWN, PivotStrength.MAJOR, 0, datetime.now(timezone.utc))
    trade = TradeState(
        id="T5",
        is_open=True,
        direction=Direction.UP,
        setup_class=SetupClass.TRAP,
        entry_price=101.0,
        pivot_used=pivot,
        position_size=10.0,
        initial_position_size=10.0,
    )
    atr = 10.0
    from bot.config import STALL_ATR_MULT, TRAP_REENTRY_ATR_MULT
    
    # 1. Price moves away -> dist_from_entry > STALL_ATR_MULT * atr
    # STALL_ATR_MULT is typically 0.5. Dist must be > 5.0
    price_away = 107.0
    check_stalling(trade, price_away, atr)
    
    assert trade.trap_moved_away == True
    assert trade.stalling_flag == False
    assert trade.position_size == 10.0
    
    # 2. Price returns to trigger zone -> dist_from_pivot <= TRAP_REENTRY_ATR_MULT * atr
    # TRAP_REENTRY_ATR_MULT is 2.0. Dist from pivot (100) must be <= 20.0
    # dist_from_entry (101) must also be NOT stalling? Actually proxy A and C are independent.
    price_return = 105.0 # dist to pivot = 5.0 <= 20.0
    check_stalling(trade, price_return, atr)
    
    assert trade.stalling_flag == True
    # Reduces position by 50%
    assert trade.position_size == 5.0
    assert len(trade.partials_taken) == 1
    assert trade.partials_taken[0].fraction == 0.5
