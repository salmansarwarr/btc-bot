"""
Tests for market context: HTF bias and Pivot Registry.
"""
import pytest
from datetime import datetime, timezone, timedelta

from bot.structs import OHLCV_Bar, PivotFlag, PivotStrength, Direction, BiasState
from bot.market_context import htf_bias, pivot_registry
from bot.data_ingestion import ohlcv_buffer
from bot.indicators import registry

def build_bar(ts: datetime, o: float, h: float, l: float, c: float) -> OHLCV_Bar:
    return OHLCV_Bar(
        timestamp=ts,
        open=o, high=h, low=l, close=c,
        volume=100.0, timeframe="D1", asset="TEST"
    )

@pytest.fixture(autouse=True)
def setup_teardown():
    # Setup
    ohlcv_buffer.buffer.clear()
    pivot_registry.pivot_registry.clear()
    registry.Indicators.clear()
    registry._buffers.clear()
    htf_bias.htf_bias.clear()
    yield
    # Teardown
    ohlcv_buffer.buffer.clear()
    pivot_registry.pivot_registry.clear()
    registry.Indicators.clear()
    registry._buffers.clear()
    htf_bias.htf_bias.clear()

def test_bias_neutral_no_msb_within_20_bars():
    # Create 30 bars, no major pivots
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for i in range(30):
        bar = build_bar(base_ts + timedelta(days=i), 100, 101, 99, 100)
        ohlcv_buffer.on_bar_close(bar)
        pivot_registry.update_pivot_registry("TEST", "D1")
        
    htf_bias.update_htf_bias("TEST")
    
    # Should be NEUTRAL because there are no major pivots, thus no MSB
    assert htf_bias.htf_bias["TEST"] == BiasState.NEUTRAL

def test_bias_msb_agrees_with_ema():
    # Setup EMA so it's trending UP
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    # Push 50 bars to warm up EMA and create an uptrend
    for i in range(50):
        c = 100 + i * 2
        bar = build_bar(base_ts + timedelta(days=i), c, c+5, c-5, c+2)
        ohlcv_buffer.on_bar_close(bar)
        
    # We need to manually manipulate the indicator state to ensure EMA matches what we want
    # because 50 bars is the bare minimum for EMA to start producing values, let's just 
    # force the EMA state for simplicity of the test.
    ind_state = registry.get_or_create("TEST", "D1")
    ind_state.ema_50 = 200.0
    # Lagged EMA must be < current EMA for BULLISH slope
    ind_state.ema_50_buffer.extend([150.0] * 15)  
    
    # Inject a MAJOR swing high in the past
    p_ts = base_ts + timedelta(days=40)
    pivot = PivotFlag(
        asset="TEST", timeframe="D1", price=120.0, direction=Direction.UP,
        strength=PivotStrength.MAJOR, bar_index=40, timestamp=p_ts
    )
    pivot_registry.pivot_registry["TEST"] = {"D1": [pivot]}
    
    # Push a bar that breaks this high (close > 120)
    break_bar = build_bar(base_ts + timedelta(days=51), 100, 150, 90, 130)
    ohlcv_buffer.on_bar_close(break_bar)
    
    # Update bias
    htf_bias.update_htf_bias("TEST")
    
    # MSB was BULLISH (broke resistance), EMA is BULLISH (200 > 150)
    assert htf_bias.htf_bias["TEST"] == BiasState.BULLISH

def test_bias_neutral_when_ema_conflicts():
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    # Warm up buffer
    for i in range(50):
        bar = build_bar(base_ts + timedelta(days=i), 100, 101, 99, 100)
        ohlcv_buffer.on_bar_close(bar)
        
    # Force indicator state for BEARISH EMA
    ind_state = registry.get_or_create("TEST", "D1")
    ind_state.ema_50 = 100.0
    ind_state.ema_50_buffer.extend([150.0] * 15)  # lagged is 150 -> down slope
    
    # Inject a MAJOR swing high in the past
    p_ts = base_ts + timedelta(days=40)
    pivot = PivotFlag(
        asset="TEST", timeframe="D1", price=120.0, direction=Direction.UP,
        strength=PivotStrength.MAJOR, bar_index=40, timestamp=p_ts
    )
    pivot_registry.pivot_registry["TEST"] = {"D1": [pivot]}
    
    # Push a bar that breaks this high (close > 120), meaning BULLISH MSB
    break_bar = build_bar(base_ts + timedelta(days=51), 100, 150, 90, 130)
    ohlcv_buffer.on_bar_close(break_bar)
    
    # Update bias
    htf_bias.update_htf_bias("TEST")
    
    # MSB is BULLISH, but EMA is BEARISH -> Conflict -> NEUTRAL
    assert htf_bias.htf_bias["TEST"] == BiasState.NEUTRAL

def test_first_reaction_confirmed():
    base_ts = datetime(2024, 1, 1, tzinfo=timezone.utc)
    
    for i in range(10):
        bar = build_bar(base_ts + timedelta(days=i), 100, 101, 99, 100)
        ohlcv_buffer.on_bar_close(bar)
        
    # Force ATR to 2.0
    ind_state = registry.get_or_create("TEST", "D1")
    ind_state.atr_14 = 2.0
    
    # Inject a MINOR support pivot at 90.0
    pivot = PivotFlag(
        asset="TEST", timeframe="D1", price=90.0, direction=Direction.DOWN,
        strength=PivotStrength.MINOR, bar_index=5, timestamp=base_ts,
        first_reaction_confirmed=False
    )
    pivot_registry.pivot_registry["TEST"] = {"D1": [pivot]}
    
    # Push a bar that approaches and reverses.
    # Pivot is 90.0. Approach dist = 0.1 * 2.0 = 0.2. So low <= 90.2
    # Reversal req = 0.25 * 2.0 = 0.5. So close - low >= 0.5
    
    # Meets both: low=90.1 (approached), close=91.0 (reversed by 0.9)
    approach_bar = build_bar(base_ts + timedelta(days=11), 95.0, 96.0, 90.1, 91.0)
    ohlcv_buffer.on_bar_close(approach_bar)
    
    # Call check_first_reaction
    pivot_registry.check_first_reaction("TEST", "D1")
    
    # Should be set to True
    assert pivot_registry.pivot_registry["TEST"]["D1"][0].first_reaction_confirmed is True
