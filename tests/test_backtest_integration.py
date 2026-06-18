import pytest
from datetime import datetime, timezone, timedelta
from bot.structs import OHLCV_Bar, AssetConfig
from bot.backtesting.engine import BacktestEngine

def _make_bars(days: int = 14) -> list[OHLCV_Bar]:
    bars = []
    base_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    price = 100.0
    
    # 24 bars per day for H1
    for i in range(days * 24):
        now = base_time + timedelta(hours=i)
        
        # We want to create some swings so it triggers setups
        import math
        # Simple sine wave to create pivots
        price_change = math.sin(i / 6.0) * 5.0 
        price += price_change
        
        # Add some trend upward
        price += 0.5
        
        b = OHLCV_Bar(
            asset="BTC",
            timeframe="H1",
            timestamp=now,
            open=price,
            high=price + 2.0,
            low=price - 2.0,
            close=price + 1.0, # Slight up close
            volume=1000.0
        )
        bars.append(b)
        
    # Also add some D1 bars so capitulation doesn't error out
    d1_bars = []
    daily_price = 100.0
    for i in range(days):
        now = base_time + timedelta(days=i)
        b = OHLCV_Bar(
            asset="BTC",
            timeframe="D1",
            timestamp=now,
            open=daily_price,
            high=daily_price + 10.0,
            low=daily_price - 10.0,
            close=daily_price + 2.0,
            volume=24000.0
        )
        daily_price += 2.0
        d1_bars.append(b)
        
    return d1_bars + bars

def test_engine_runs_without_errors():
    engine = BacktestEngine(initial_equity=100000.0)
    config = AssetConfig(symbol="BTC")
    engine.add_asset_config(config)
    
    bars = _make_bars(days=20)
    
    # Pre-feed D1 bars first
    for b in bars:
        if b.timeframe == "D1":
            engine.step(b, oi=1000.0, liq=50.0)
            
    # Now feed H1 bars
    for b in bars:
        if b.timeframe == "H1":
            engine.step(b, oi=1000.0, liq=50.0)
            
    # Check that it didn't crash
    stats = engine.get_summary_stats()
    assert "total_trades" in stats
    if stats["total_trades"] > 0:
        assert "win_rate" in stats
    
    # Depending on exactly what setups triggered, we might or might not have trades
    # But it ran end-to-end
    print(stats)
