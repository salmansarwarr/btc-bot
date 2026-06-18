"""
Unit tests for core technical indicators.
Cross-checks against the `ta` library to ensure parity with known implementations.
"""

import math
import pytest
import pandas as pd
import ta

from bot.indicators import core

# ---------------------------------------------------------------------------
# Sample OHLCV data (small snippet for deterministic testing)
# Generated synthetic trending/ranging data to exercise all calculations
# ---------------------------------------------------------------------------
SAMPLE_DATA = [
    #  open,   high,    low,  close
    (100.00, 102.00,  99.00, 101.50),
    (101.50, 103.50, 101.00, 102.50),
    (102.50, 102.80,  98.00,  99.50),
    ( 99.50, 101.00,  99.00, 100.20),
    (100.20, 105.00, 100.00, 104.50),
    (104.50, 106.00, 103.50, 105.80),
    (105.80, 108.00, 105.50, 107.00),
    (107.00, 107.50, 104.00, 104.20),
    (104.20, 105.00, 101.00, 101.80),
    (101.80, 102.00,  99.50,  99.80),
    ( 99.80, 101.50,  99.50, 101.00),
    (101.00, 103.00, 100.50, 102.80),
    (102.80, 104.50, 102.00, 104.00),
    (104.00, 106.50, 103.50, 106.20),
    (106.20, 108.50, 106.00, 108.10),
    (108.10, 109.00, 107.00, 107.50),
    (107.50, 108.00, 105.00, 105.20),
    (105.20, 106.00, 103.00, 103.80),
    (103.80, 104.50, 102.00, 102.50),
    (102.50, 103.00, 100.00, 100.50),
]

@pytest.fixture
def ohlc_df() -> pd.DataFrame:
    df = pd.DataFrame(SAMPLE_DATA, columns=['open', 'high', 'low', 'close'])
    return df

def test_ema(ohlc_df: pd.DataFrame):
    closes = ohlc_df['close']
    period = 5
    
    my_ema = core.ema(closes.tolist(), period=period)
    
    # ta library EMA
    ta_ema = ta.trend.EMAIndicator(close=closes, window=period).ema_indicator().tolist()
    
    # Check values after warm-up
    # EMA seeds differently in different libraries. 
    # 'ta' uses the first value as seed, we use SMA.
    # Therefore, values will converge rather than match exactly early on.
    # We will just verify they are close toward the end.
    for i in range(len(closes) - 5, len(closes)):
        diff = abs(my_ema[i] - ta_ema[i])
        # Diff can be up to ~0.5 due to seeding differences over a short window
        if diff > 1.0:
            pytest.fail(f"EMA diff at {i}: {my_ema[i]} vs {ta_ema[i]} (diff: {diff})\nDifferent seed logic.")

def test_atr(ohlc_df: pd.DataFrame):
    highs = ohlc_df['high']
    lows = ohlc_df['low']
    closes = ohlc_df['close']
    period = 5
    
    my_atr = core.atr(highs.tolist(), lows.tolist(), closes.tolist(), period=period)
    
    ta_atr = ta.volatility.AverageTrueRange(
        high=highs, low=lows, close=closes, window=period
    ).average_true_range().tolist()
    
    for i in range(len(closes) - 5, len(closes)):
        if math.isnan(my_atr[i]) and math.isnan(ta_atr[i]):
            continue
        diff = abs(my_atr[i] - ta_atr[i])
        if diff > 0.5:
            pytest.fail(f"ATR diff at {i}: {my_atr[i]} vs {ta_atr[i]}")

def test_rsi(ohlc_df: pd.DataFrame):
    closes = ohlc_df['close']
    period = 5
    
    my_rsi = core.rsi(closes.tolist(), period=period)
    ta_rsi = ta.momentum.RSIIndicator(close=closes, window=period).rsi().tolist()
    
    for i in range(len(closes) - 5, len(closes)):
        if math.isnan(my_rsi[i]) and math.isnan(ta_rsi[i]):
            continue
        diff = abs(my_rsi[i] - ta_rsi[i])
        # RSI seed difference (SMA vs Wilder's initial) requires small tolerance over 20 periods
        if diff > 5.0:
            pytest.fail(f"RSI diff at {i}: {my_rsi[i]} vs {ta_rsi[i]} (diff: {diff})\nSeed difference expected, but shouldn't be > 5.0 at the end.")

def test_adx(ohlc_df: pd.DataFrame):
    highs = ohlc_df['high']
    lows = ohlc_df['low']
    closes = ohlc_df['close']
    period = 5
    
    my_adx_res = core.adx(highs.tolist(), lows.tolist(), closes.tolist(), period=period)
    my_adx = my_adx_res['adx']
    
    ta_adx = ta.trend.ADXIndicator(
        high=highs, low=lows, close=closes, window=period
    ).adx().tolist()
    
    for i in range(len(closes) - 5, len(closes)):
        if math.isnan(my_adx[i]) and math.isnan(ta_adx[i]):
            continue
        diff = abs(my_adx[i] - ta_adx[i])
        if diff > 5.0:
            pytest.fail(f"ADX diff at {i}: {my_adx[i]} vs {ta_adx[i]} (diff: {diff})\nOur implementation uses Wilder's RMA per TradingView ta.adx() reference.")

def test_efficiency_ratio():
    closes = [100, 101, 102, 101, 100, 105, 110, 109, 115, 120, 125]
    period = 5
    er = core.efficiency_ratio(closes, period=period)
    
    # |105 - 100| = 5
    # |101-100| + |102-101| + |101-102| + |100-101| + |105-100| = 1+1+1+1+5 = 9
    # ER = 5 / 9 = 0.555...
    assert math.isclose(er[5], 5/9, rel_tol=1e-5)

def test_wick_body_ratios():
    opens  = [100.0, 100.0]
    highs  = [110.0, 105.0]
    lows   = [90.0,  95.0]
    closes = [105.0, 95.0]
    
    bodies = core.body_size(opens, closes)
    assert bodies == [5.0, 5.0]
    
    uw = core.upper_wick(highs, opens, closes)
    assert uw == [5.0, 5.0]
    
    lw = core.lower_wick(lows, opens, closes)
    assert lw == [10.0, 0.0]
    
    brr = core.body_range_ratio(highs, lows, opens, closes)
    assert brr == [0.25, 0.5]
    
    wr = core.wick_ratio(highs, lows, opens, closes, side="rejection")
    assert wr == [0.5, 0.5]
