import pytest
from datetime import datetime, timezone
from bot.structs import SetupCandidate, SetupType, Direction, PivotFlag, PivotStrength
from bot.config import SR_FLIP_STOP_ATR_MULT, MIN_STOP_ATR_MULT
from bot.entry_risk.stop_calculator import compute_stop

def test_compute_stop_sr_flip():
    # Pivot = 100
    # Entry = 105
    # ATR = 10
    # SR_FLIP stop offset = SR_FLIP_STOP_ATR_MULT * 10 (e.g. 0.15 * 10 = 1.5)
    # Stop = 100 - 1.5 = 98.5
    # Min stop = 105 - 10 = 95
    # Max allowed stop (closest to entry) = 95
    # So stop must be pushed down to 95 to satisfy MIN_STOP_ATR_MULT!
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 100.0, Direction.UP, PivotStrength.MAJOR, 0, t0)
    
    cand_up = SetupCandidate(
        setup_type=SetupType.SR_FLIP,
        direction=Direction.UP,
        trigger_pivot=pivot,
        trigger_price=105.0
    )
    
    atr = 10.0
    stop = compute_stop(cand_up, atr)
    
    # 100 - 1.5 = 98.5. 105 - 10 = 95.0. min(98.5, 95.0) = 95.0
    expected_stop = min(pivot.price - (SR_FLIP_STOP_ATR_MULT * atr), cand_up.trigger_price - (MIN_STOP_ATR_MULT * atr))
    assert stop == expected_stop
    
    # What if entry is 120? min stop = 120 - 10 = 110. But pivot is 100, stop is 98.5.
    # min(98.5, 110) = 98.5
    cand_up_far = SetupCandidate(
        setup_type=SetupType.SR_FLIP,
        direction=Direction.UP,
        trigger_pivot=pivot,
        trigger_price=120.0
    )
    stop_far = compute_stop(cand_up_far, atr)
    assert stop_far == pivot.price - (SR_FLIP_STOP_ATR_MULT * atr)

def test_compute_stop_msb():
    # MSB_SHALLOW or DEEP
    # Origin pivot = 100
    # Entry = 110
    # ATR = 10
    # Stop should be origin_pivot - MIN_STOP_ATR_MULT * ATR = 100 - 10 = 90
    # Min stop = 110 - 10 = 100
    # min(90, 100) = 90
    t0 = datetime.now(timezone.utc)
    pivot = PivotFlag("BTC", "H1", 100.0, Direction.DOWN, PivotStrength.MAJOR, 0, t0)
    
    cand = SetupCandidate(
        setup_type=SetupType.MSB_SHALLOW,
        direction=Direction.UP,
        trigger_pivot=pivot,
        trigger_price=110.0
    )
    
    atr = 10.0
    stop = compute_stop(cand, atr)
    
    expected_stop = pivot.price - (MIN_STOP_ATR_MULT * atr)
    assert stop == expected_stop

def test_compute_stop_fallback():
    # OPEN_DRIVE or any other
    # Entry = 100
    # ATR = 10
    # Stop = entry - MIN_STOP_ATR_MULT * ATR = 90
    cand = SetupCandidate(
        setup_type=SetupType.OPEN_DRIVE,
        direction=Direction.UP,
        trigger_price=100.0
    )
    
    atr = 10.0
    stop = compute_stop(cand, atr)
    
    expected_stop = cand.trigger_price - (MIN_STOP_ATR_MULT * atr)
    assert stop == expected_stop

def test_compute_stop_down_direction():
    # SFP Short
    # Entry = 100
    # ATR = 10
    # Stop = 100 + 10 = 110
    cand = SetupCandidate(
        setup_type=SetupType.SFP,
        direction=Direction.DOWN,
        trigger_price=100.0
    )
    
    atr = 10.0
    stop = compute_stop(cand, atr)
    
    expected_stop = cand.trigger_price + (MIN_STOP_ATR_MULT * atr)
    assert stop == expected_stop
