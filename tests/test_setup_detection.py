import pytest
from datetime import datetime, timezone, timedelta
from bot.structs import OHLCV_Bar, PivotFlag, PivotStrength, Direction, SetupType, SetupClass
from bot.setup_detection.clean_break import detect_clean_break
from bot.setup_detection.sr_flip import detect_sr_flip
from bot.setup_detection.cdc import detect_cdc
from bot.setup_detection.msb_pullback import detect_msb_pullback
from bot.setup_detection.open_drive import detect_open_drive
from bot.setup_detection.sfp import detect_sfp
from bot.setup_detection.liquidation_flush import detect_liquidation_flush
from bot.setup_detection.consolidation import detect_consolidation
from bot.setup_detection.momentum_divergence import detect_momentum_divergence
from bot.setup_detection.runner import run_setup_detection
from bot.structs import AssetConfig, ExternalFeedState, LiquidationProxyMethod, MarketBasket, TrendClass
from bot.config import (
    BREAK_BODY_ATR_MULT, BREAK_CLOSE_BEYOND_ATR_MULT, BREAK_WICK_RATIO_MAX,
    SR_FLIP_STOP_ATR_MULT, CDC_NO_INTERACTION_ATR_MULT, MIN_STOP_ATR_MULT,
    DRIVE_ATR_MULT, DRIVE_BODY_RANGE_RATIO_MIN
)

def test_clean_break_up():
    atr = 100.0
    level = 50000.0
    
    # Needs to satisfy:
    # 1. body size >= BREAK_BODY_ATR_MULT * atr
    # 2. close >= level + BREAK_CLOSE_BEYOND_ATR_MULT * atr
    # 3. top wick / total range <= BREAK_WICK_RATIO_MAX
    
    body_req = BREAK_BODY_ATR_MULT * atr
    close_req = level + (BREAK_CLOSE_BEYOND_ATR_MULT * atr)
    
    open_p = level - body_req
    close_p = close_req + 10  # safely beyond
    high_p = close_p + 10 # small top wick
    low_p = open_p - 10 # small bottom wick
    
    bar = OHLCV_Bar(
        timestamp=datetime.now(timezone.utc),
        open=open_p,
        high=high_p,
        low=low_p,
        close=close_p,
        volume=100.0,
        timeframe="H1",
        asset="BTC"
    )
    
    assert detect_clean_break(bar, level, Direction.UP, atr) is True

    # Test failure: top wick too long
    bad_wick_high = close_p + 1000
    bar_bad_wick = OHLCV_Bar(
        timestamp=datetime.now(timezone.utc),
        open=open_p,
        high=bad_wick_high,
        low=low_p,
        close=close_p,
        volume=100.0,
        timeframe="H1",
        asset="BTC"
    )
    assert detect_clean_break(bar_bad_wick, level, Direction.UP, atr) is False
    
    # Test failure: close not far enough beyond
    bar_bad_close = OHLCV_Bar(
        timestamp=datetime.now(timezone.utc),
        open=open_p,
        high=high_p,
        low=low_p,
        close=level + (BREAK_CLOSE_BEYOND_ATR_MULT * atr) - 1, # not enough
        volume=100.0,
        timeframe="H1",
        asset="BTC"
    )
    assert detect_clean_break(bar_bad_close, level, Direction.UP, atr) is False

def test_detect_sr_flip():
    atr = 100.0
    level = 50000.0
    
    t0 = datetime.now(timezone.utc)
    
    # 1. Pivot at level (Resistance)
    pivot = PivotFlag(
        asset="BTC",
        timeframe="H1",
        price=level,
        direction=Direction.UP,
        strength=PivotStrength.MAJOR,
        bar_index=0,
        timestamp=t0
    )
    
    bars = []
    
    # Bar 1: Clean break UP
    b1_open = level - 150
    b1_close = level + 50 # 50 >= BREAK_CLOSE_BEYOND_ATR_MULT(0.15) * 100 (15)
    b1_high = b1_close + 5
    b1_low = b1_open - 5
    
    bars.append(OHLCV_Bar(t0 + timedelta(hours=1), b1_open, b1_high, b1_low, b1_close, 100.0, "H1", "BTC"))
    
    # Bar 2: Pullback touching the level
    b2_open = b1_close
    b2_close = level + 10
    b2_low = level - 10 # Drops below level to touch it
    b2_high = b2_open + 10
    
    bars.append(OHLCV_Bar(t0 + timedelta(hours=2), b2_open, b2_high, b2_low, b2_close, 100.0, "H1", "BTC"))
    
    # Bar 3: Bounce (Close > Open)
    b3_open = b2_close
    b3_close = b3_open + 50
    b3_low = b3_open - 5
    b3_high = b3_close + 5
    
    bars.append(OHLCV_Bar(t0 + timedelta(hours=3), b3_open, b3_high, b3_low, b3_close, 100.0, "H1", "BTC"))
    
    cands = detect_sr_flip(bars, [pivot], atr)
    
    assert len(cands) == 1
    setup = cands[0]
    assert setup.setup_type == SetupType.SR_FLIP
    assert setup.direction == Direction.UP
    assert setup.trigger_price == b3_close
    assert setup.stop_price == level - (SR_FLIP_STOP_ATR_MULT * atr)

def test_detect_cdc_and_pattern_failure():
    atr = 100.0
    level = 50000.0
    
    t0 = datetime.now(timezone.utc)
    
    # Resistance pivot
    pivot = PivotFlag(
        asset="BTC",
        timeframe="H1",
        price=level,
        direction=Direction.UP,
        strength=PivotStrength.MAJOR,
        bar_index=0,
        timestamp=t0
    )
    
    bars = []
    
    # Bar 1: Clean break UP
    b1_open = level - 150
    b1_close = level + 50 
    b1_high = b1_close + 5
    b1_low = b1_open - 5
    bars.append(OHLCV_Bar(t0 + timedelta(hours=1), b1_open, b1_high, b1_low, b1_close, 100.0, "H1", "BTC"))
    
    # Bar 2: Drift (pulls back but no interaction)
    # Allowed intrusion: 0.05 * 100 = 5
    # So low must be > level - 5
    b2_open = b1_close
    b2_close = b2_open - 20
    b2_low = level + 10 # Safely above level
    b2_high = b2_open + 5
    bars.append(OHLCV_Bar(t0 + timedelta(hours=2), b2_open, b2_high, b2_low, b2_close, 100.0, "H1", "BTC"))
    
    # Bar 3: Close (bullish)
    b3_open = b2_close
    b3_close = b3_open + 30
    b3_low = b3_open - 5
    b3_high = b3_close + 5
    bars.append(OHLCV_Bar(t0 + timedelta(hours=3), b3_open, b3_high, b3_low, b3_close, 100.0, "H1", "BTC"))
    
    # Test CDC
    cands_cdc = detect_cdc(bars, [pivot], atr, include_pattern_failure=False)
    assert len(cands_cdc) == 1
    setup = cands_cdc[0]
    assert setup.setup_type == SetupType.CDC
    assert setup.direction == Direction.UP
    assert setup.is_pattern_failure_mode is False
    assert setup.cdc_qualifies_zero_tolerance is True # lowest was level + 10
    
    # Now let's test Pattern Failure on a DIFFERENT Bar 3
    bars.pop() # Remove the bullish Bar 3
    
    # Bar 3 (Alternative): Clean break DOWN
    b3_alt_open = b2_close
    b3_alt_close = level - 80 # Cleanly breaks the level down (body > 100)
    b3_alt_high = b3_alt_open + 5
    b3_alt_low = b3_alt_close - 5
    bars.append(OHLCV_Bar(t0 + timedelta(hours=3), b3_alt_open, b3_alt_high, b3_alt_low, b3_alt_close, 100.0, "H1", "BTC"))
    
    cands_pf = detect_cdc(bars, [pivot], atr, include_pattern_failure=True)
    assert len(cands_pf) == 1
    setup_pf = cands_pf[0]
    assert setup_pf.setup_type == SetupType.PATTERN_FAILURE
    assert setup_pf.direction == Direction.DOWN
    assert setup_pf.is_pattern_failure_mode is True
    assert setup_pf.cdc_qualifies_zero_tolerance is True

def test_detect_msb_pullback():
    atr = 100.0
    t0 = datetime.now(timezone.utc)
    
    # We need a DOWN pivot (swing origin) and an UP pivot (the broken resistance)
    origin_price = 40000.0
    origin_pivot = PivotFlag("BTC", "H1", origin_price, Direction.DOWN, PivotStrength.MAJOR, 0, t0)
    
    break_level = 50000.0
    break_pivot = PivotFlag("BTC", "H1", break_level, Direction.UP, PivotStrength.MAJOR, 10, t0 + timedelta(hours=10))
    
    pivots = [origin_pivot, break_pivot]
    bars = []
    
    # Time t1: Clean break UP
    t1 = t0 + timedelta(hours=15)
    bars.append(OHLCV_Bar(t1, break_level - 150, break_level + 150, break_level - 160, break_level + 100, 100, "H1", "BTC"))
    
    # Time t2: Swing High established
    t2 = t1 + timedelta(hours=1)
    swing_high = 55000.0
    bars.append(OHLCV_Bar(t2, break_level + 100, swing_high, break_level + 50, swing_high - 100, 100, "H1", "BTC"))
    
    # Total swing = swing_high - origin_price = 55000 - 40000 = 15000
    # Shallow fib (0.236 to 0.382) -> depth between 3540 and 5730. Pullback low between 51460 and 49270.
    # But SHALLOW_ATR_CAP_MULT is 3.0 * ATR = 300. 
    # Wait, our swing is 15000, so a shallow pullback is 3540 points. That's > 300 points!
    # So it will fail the SHALLOW_ATR_CAP_MULT check unless we make the swing smaller or ATR larger.
    # Let's set ATR = 2000.0
    atr = 2000.0
    
    # Time t3: Pullback candle (Shallow)
    t3 = t2 + timedelta(hours=1)
    pullback_low = swing_high - 4000 # Depth = 4000. Fib = 4000 / 15000 = 0.266 (Shallow!). Cap = 3.0 * 2000 = 6000.
    bars.append(OHLCV_Bar(t3, swing_high - 100, swing_high - 50, pullback_low, pullback_low + 50, 100, "H1", "BTC"))
    
    # Time t4: Resolution bounce
    t4 = t3 + timedelta(hours=1)
    bars.append(OHLCV_Bar(t4, pullback_low + 50, pullback_low + 500, pullback_low, pullback_low + 400, 100, "H1", "BTC"))
    
    cands_shallow = detect_msb_pullback(bars, pivots, atr)
    assert len(cands_shallow) == 1
    setup = cands_shallow[0]
    assert setup.setup_type == SetupType.MSB_SHALLOW
    assert setup.direction == Direction.UP
    assert setup.stop_price == pullback_low - (MIN_STOP_ATR_MULT * atr)
    
    # Now let's test a DEEP pullback (0.55 to 0.85)
    # Depth between 8250 and 12750. Pullback low between 46750 and 42250.
    bars.pop() # Remove resolution candle
    bars.pop() # Remove shallow pullback candle
    
    t3_deep = t2 + timedelta(hours=1)
    pullback_low_deep = swing_high - 10000 # Depth = 10000. Fib = 10000 / 15000 = 0.666 (Deep!)
    bars.append(OHLCV_Bar(t3_deep, swing_high - 100, swing_high - 50, pullback_low_deep, pullback_low_deep + 50, 100, "H1", "BTC"))
    
    t4_deep = t3_deep + timedelta(hours=1)
    bars.append(OHLCV_Bar(t4_deep, pullback_low_deep + 50, pullback_low_deep + 500, pullback_low_deep, pullback_low_deep + 400, 100, "H1", "BTC"))
    
    cands_deep = detect_msb_pullback(bars, pivots, atr)
    assert len(cands_deep) == 1
    setup_deep = cands_deep[0]
    assert setup_deep.setup_type == SetupType.MSB_DEEP
    assert setup_deep.direction == Direction.UP
    assert setup_deep.stop_price == pullback_low_deep - (MIN_STOP_ATR_MULT * atr)

def test_detect_open_drive():
    atr = 100.0
    level = 50000.0
    t0 = datetime.now(timezone.utc)
    
    # Support pivot
    pivot = PivotFlag("BTC", "H1", level, Direction.DOWN, PivotStrength.MAJOR, 0, t0)
    
    # Case 1: Open near pivot and drive away (Bounce)
    open_p = level + 20 # within MIN_STOP_ATR_MULT (0.5 * 100 = 50)
    close_p = open_p + (DRIVE_ATR_MULT * atr) + 10 # body size 110 >= 100
    low_p = open_p - 10 # 10 pt bottom wick
    high_p = close_p + 10 # 10 pt top wick
    
    # Body = 110. Range = 130. Ratio = 110/130 = 0.846 >= 0.6. Valid Open Drive!
    bar = OHLCV_Bar(t0 + timedelta(hours=1), open_p, high_p, low_p, close_p, 100, "H1", "BTC")
    
    cands = detect_open_drive([bar], [pivot], atr)
    assert len(cands) == 1
    assert cands[0].setup_type == SetupType.OPEN_DRIVE
    assert cands[0].direction == Direction.UP
    assert cands[0].setup_class == SetupClass.REVERSAL
    
    # Case 2: Clean break of a resistance pivot
    res_pivot = PivotFlag("BTC", "H1", level, Direction.UP, PivotStrength.MAJOR, 0, t0)
    open_p2 = level - 50 # Below resistance
    close_p2 = open_p2 + 150 # Closes above resistance at 50100 (body 150)
    low_p2 = open_p2 - 5
    high_p2 = close_p2 + 5
    
    bar2 = OHLCV_Bar(t0 + timedelta(hours=1), open_p2, high_p2, low_p2, close_p2, 100, "H1", "BTC")
    cands2 = detect_open_drive([bar2], [res_pivot], atr)
    assert len(cands2) == 1
    assert cands2[0].direction == Direction.UP
    assert cands2[0].setup_class == SetupClass.CONTINUATION

def test_detect_sfp():
    atr = 100.0
    level = 50000.0
    t0 = datetime.now(timezone.utc)
    
    # Resistance pivot
    pivot = PivotFlag("BTC", "H1", level, Direction.UP, PivotStrength.MAJOR, 0, t0)
    
    bars = []
    # Bar 1: approaches level but doesn't sweep
    bars.append(OHLCV_Bar(t0 + timedelta(hours=1), level - 200, level - 50, level - 250, level - 100, 100, "H1", "BTC"))
    
    # Bar 2: Sweeps the level (high > level) but closes back inside (close <= level)
    bars.append(OHLCV_Bar(t0 + timedelta(hours=2), level - 100, level + 50, level - 150, level - 10, 100, "H1", "BTC"))
    
    cands = detect_sfp(bars, [pivot], atr)
    assert len(cands) == 1
    setup = cands[0]
    assert setup.setup_type == SetupType.SFP
    assert setup.setup_class == SetupClass.TRAP
    assert setup.direction == Direction.DOWN
    assert setup.stop_price == (level + 50) + (MIN_STOP_ATR_MULT * atr)
    
    # Check invalidation if already broken
    bars.pop() # Remove sweep candle
    
    # Insert a candle that breaks the level
    bars.append(OHLCV_Bar(t0 + timedelta(hours=2), level - 100, level + 200, level - 150, level + 150, 100, "H1", "BTC"))
    
    # Now insert the sweep candle (it shouldn't trigger because level was broken)
    bars.append(OHLCV_Bar(t0 + timedelta(hours=3), level + 150, level + 250, level - 10, level - 10, 100, "H1", "BTC"))
    
    cands_invalid = detect_sfp(bars, [pivot], atr)
    assert len(cands_invalid) == 0

def test_detect_liquidation_flush():
    atr = 100.0
    level = 50000.0
    t0 = datetime.now(timezone.utc)
    
    # Configure Asset & Feed
    config = AssetConfig("BTC", liquidation_proxy_method=LiquidationProxyMethod.OI_PCT)
    feed = ExternalFeedState("BTC")
    
    # Mock OI and Liquidations
    feed.oi_hourly = [1000000.0, 1000000.0]
    feed.liq_hourly = [1000.0, 25000.0] # 25000 / 1000000 = 0.025 (>= 0.02) -> SPIKE!
    
    # Support pivot
    pivot = PivotFlag("BTC", "H1", level, Direction.DOWN, PivotStrength.MAJOR, 0, t0)
    
    # Candle that dumps into support and bounces (Close > Open)
    bars = []
    bars.append(OHLCV_Bar(t0 + timedelta(hours=1), level + 200, level + 250, level - 50, level + 100, 100, "H1", "BTC"))
    
    cands = detect_liquidation_flush(bars, [pivot], atr, config, feed)
    
    assert len(cands) == 1
    setup = cands[0]
    assert setup.setup_type == SetupType.LIQUIDATION_FLUSH
    assert setup.setup_class == SetupClass.REVERSAL
    assert setup.direction == Direction.UP
    assert setup.trigger_pivot == pivot
    assert setup.stop_price == (level - 50) - (MIN_STOP_ATR_MULT * atr)
    
    # Test fallback: No spike, no setup
    feed_no_spike = ExternalFeedState("BTC")
    feed_no_spike.oi_hourly = [1000000.0, 1000000.0]
    feed_no_spike.liq_hourly = [1000.0, 5000.0] # 0.005 < 0.02 -> NO SPIKE
    
    cands_empty = detect_liquidation_flush(bars, [pivot], atr, config, feed_no_spike)
    assert len(cands_empty) == 0

def test_detect_consolidation():
    atr = 100.0
    t0 = datetime.now(timezone.utc)
    bars = []
    
    # Add 5 consolidation bars (ranges all < 70, total height < 150)
    base_level = 50000.0
    for i in range(5):
        bars.append(OHLCV_Bar(t0 + timedelta(hours=i), base_level, base_level+20, base_level-20, base_level+10, 100, "H1", "BTC"))
        
    # Breakout bar (UP)
    b_open = base_level + 10
    b_close = base_level + 150 # body 140 >= 100
    b_low = b_open - 5
    b_high = b_close + 5
    bars.append(OHLCV_Bar(t0 + timedelta(hours=5), b_open, b_high, b_low, b_close, 100, "H1", "BTC"))
    
    cands = detect_consolidation(bars, atr)
    assert len(cands) == 1
    assert cands[0].setup_type == SetupType.CONSOLIDATION_ENTRY
    assert cands[0].direction == Direction.UP

def test_detect_momentum_divergence(monkeypatch):
    atr = 100.0
    t0 = datetime.now(timezone.utc)
    bars = []
    
    # We need 15 bars for RSI to compute. We'll mock the RSI calculation instead to keep it simple.
    import bot.indicators.core as core
    def mock_rsi(closes, period):
        # Return dummy RSI values matching the bars length
        # Let's say we have 20 bars.
        # Bar 5 is the prev_low (price 40000, RSI 30)
        # Bar 19 is the current_bar (price 39000, RSI 45, close > open)
        rsis = [50.0] * len(closes)
        if len(rsis) >= 20:
            rsis[5] = 30.0 # Prev RSI low (< 35)
            rsis[-1] = 45.0 # Current RSI (higher than prev)
        return rsis
        
    monkeypatch.setattr(core, "rsi", mock_rsi)
    
    # Add 19 dummy bars
    for i in range(19):
        # Make bar 5 the lowest low (40000)
        low_p = 40000.0 if i == 5 else 50000.0
        bars.append(OHLCV_Bar(t0 + timedelta(hours=i), 50500, 51000, low_p, 50800, 100, "H1", "BTC"))
        
    # Bar 20: Current bar makes a new price low (39000), closes bullishly (39500 > 39000)
    bars.append(OHLCV_Bar(t0 + timedelta(hours=19), 39000, 39600, 39000, 39500, 100, "H1", "BTC"))
    
    cands = detect_momentum_divergence(bars, atr)
    assert len(cands) == 1
    assert cands[0].setup_type == SetupType.MOMENTUM_DIVERGENCE
    assert cands[0].direction == Direction.UP

def test_run_setup_detection_orchestrator():
    atr = 100.0
    t0 = datetime.now(timezone.utc)
    bars = []
    
    # Create 25 hours of history so we can calculate 24h change
    # T0 price = 50000. T24 price = 48000. (-4% change)
    for i in range(25):
        price = 50000.0 - (i * (2000.0/24.0)) # Gradual decline
        bars.append(OHLCV_Bar(t0 + timedelta(hours=i), price, price+100, price-100, price, 100, "H1", "BTC"))
        
    # Inject a clean break setup at the very end
    # Resistance pivot at 47900
    pivots = [PivotFlag("BTC", "H1", 47900.0, Direction.UP, PivotStrength.MAJOR, 0, t0)]
    
    # Current bar cleanly breaks resistance UP
    b_open = 47800.0
    b_close = 48100.0 # Clean break UP
    b_low = b_open - 10
    b_high = b_close + 10
    bars.append(OHLCV_Bar(t0 + timedelta(hours=25), b_open, b_high, b_low, b_close, 100, "H1", "BTC"))
    
    config = AssetConfig("BTC")
    feed = ExternalFeedState("BTC")
    
    # Scenario 1: Red market day (-2% BTC/ETH). Asset is at -4%. Asset underperforms!
    market_red = MarketBasket(btc_eth_avg_24h_change=-0.02)
    
    # A) In TRENDING, filter is ignored. Should return the setup.
    cands_trending = run_setup_detection(bars, pivots, atr, config, feed, market_red, TrendClass.TRENDING)
    assert len(cands_trending) == 1
    
    # B) In LOCKOUT_TREND + UP candidate + Red Market underperforming -> VETO.
    cands_lockout_red = run_setup_detection(bars, pivots, atr, config, feed, market_red, TrendClass.LOCKOUT_TREND)
    assert len(cands_lockout_red) == 0 # Filtered out!
    
    # Scenario 2: Green market day (+2%). Even though asset is down, filter passes on green days.
    market_green = MarketBasket(btc_eth_avg_24h_change=0.02)
    cands_lockout_green = run_setup_detection(bars, pivots, atr, config, feed, market_green, TrendClass.LOCKOUT_TREND)
    assert len(cands_lockout_green) == 1 # Passed through!
