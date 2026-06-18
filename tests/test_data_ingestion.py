"""
Tests for data ingestion and streaming integration.
"""
import pytest
from datetime import datetime, timezone, timedelta

from bot.data_ingestion import ohlcv_buffer, market_basket, feed_manager
from bot.indicators import registry

# For the test to not be overly slow and flaky due to network, 
# we mock the fetch_historical_bars call if we don't want to hit real APIs,
# but the user requested a test that loads real data via ccxt.
# We will load a limited amount (e.g. 200 bars) to keep the test fast.

def test_streaming_ingestion_updates_indicators():
    # 1. Fetch real historical bars from binance
    # Using 'BTC/USDT' and '1h' timeframe.
    # 30 days of 1h = 720 bars. 
    
    # We will pick a specific since timestamp to ensure data exists.
    # E.g. start of May 2024.
    since_ts = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp() * 1000)
    
    # Fetch data
    bars = ohlcv_buffer.fetch_historical_bars(
        exchange_id='binance',
        symbol='BTC/USDT',
        timeframe='1h',
        since=since_ts,
        limit=720  # ~30 days
    )
    
    assert len(bars) > 0, "No bars fetched from ccxt!"
    
    # Clear registries before test
    ohlcv_buffer.buffer.clear()
    registry.Indicators.clear()
    registry._buffers.clear()
    
    # 2. Stream bars one by one
    for bar in bars:
        ohlcv_buffer.on_bar_close(bar)
        
    # 3. Verify buffer state
    buffered_bars = ohlcv_buffer.get_bars("BTC", "H1", 1000)
    assert len(buffered_bars) == min(720, ohlcv_buffer._MAX_BUFFER_LEN)
    assert buffered_bars[-1].timestamp == bars[-1].timestamp
    
    # 4. Verify indicator registry state
    ind_state = registry.get_or_create("BTC", "H1")
    
    # After ~720 hours, indicators should be fully warmed up
    assert ind_state.atr_14 > 0, "ATR should be computed"
    assert ind_state.rsi_14 > 0, "RSI should be computed"
    assert ind_state.adx > 0, "ADX should be computed"
    assert ind_state.ema_50 > 0, "EMA-50 should be computed"
    
    # Check the EMA buffer was populated
    assert len(ind_state.ema_50_buffer) == 15, "ema_50_buffer should have reached maxlen=15"
    
    # Verify ema_50_at_lag accessor
    lag_10_ema = registry.ema_50_at_lag("BTC", "H1", 10)
    assert lag_10_ema is not None
    assert lag_10_ema > 0

def test_market_basket():
    market_basket.update_basket(btc_24h=0.05, eth_24h=-0.01)
    
    assert market_basket.basket.btc_eth_avg_24h_change == 0.02
    assert market_basket.get_24h_change("BTC") == 0.05
    assert market_basket.get_24h_change("ETH") == -0.01

def test_feed_manager():
    feed_manager.feeds.clear()
    
    # Add 48 hours of OI data
    for i in range(48):
        feed_manager.update_oi("BTC", 1000.0 + i)
        
    feed = feed_manager.feeds["BTC"]
    assert len(feed.oi_hourly) == 48
    assert feed.oi_history_days == 2  # 48 // 24
