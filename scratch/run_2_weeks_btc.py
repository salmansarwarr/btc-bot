import ccxt
import pandas as pd
from datetime import datetime, timezone, timedelta
import csv
import math
import os

from bot.structs import OHLCV_Bar, AssetConfig, ExternalFeedState, MarketBasket, TrendClass, PivotFlag, PivotStrength, Direction
from bot.indicators import core
from bot.setup_detection.runner import run_setup_detection

def get_binance_data(symbol, timeframe, limit=720):
    exchange = ccxt.binance()
    bars = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    ohlcv_bars = []
    for b in bars:
        ts = datetime.fromtimestamp(b[0]/1000, tz=timezone.utc)
        ohlcv_bars.append(OHLCV_Bar(ts, b[1], b[2], b[3], b[4], b[5], timeframe, symbol.split('/')[0]))
    return ohlcv_bars

def detect_pivots(bars: list[OHLCV_Bar], n=10):
    pivots = []
    # simple N-fractal detection
    for i in range(n, len(bars)-n):
        cand = bars[i]
        window = bars[i-n:i+n+1]
        
        # High fractal
        if all(b.high <= cand.high for b in window):
            pivots.append(PivotFlag("BTC", "H1", cand.high, Direction.UP, PivotStrength.MAJOR, i, cand.timestamp))
        # Low fractal
        elif all(b.low >= cand.low for b in window):
            pivots.append(PivotFlag("BTC", "H1", cand.low, Direction.DOWN, PivotStrength.MAJOR, i, cand.timestamp))
    return pivots

if __name__ == "__main__":
    print("Fetching BTC 1h data from Binance (30 days)...")
    # 30 days = 720 hours. 
    ohlcv_bars = get_binance_data('BTC/USDT', '1h', limit=720)
    print(f"Fetched {len(ohlcv_bars)} bars.")
    
    config = AssetConfig("BTC")
    feed = ExternalFeedState("BTC")
    market = MarketBasket(btc_eth_avg_24h_change=0.01) # Allow all setups (green market)
    trend = TrendClass.TRENDING 
    
    output = []
    
    print("Running setup detection...")
    
    all_pivots = detect_pivots(ohlcv_bars, n=10)
    
    # We start from bar 200 to give enough warmup for ATR and RSI
    for i in range(200, len(ohlcv_bars)):
        window = ohlcv_bars[:i+1]
        current_bar = window[-1]
        
        closes = [b.close for b in window]
        highs = [b.high for b in window]
        lows = [b.low for b in window]
        atr_series = core.atr(highs, lows, closes, 14)
        atr = atr_series[-1]
        
        if math.isnan(atr):
            continue
            
        known_pivots = [p for p in all_pivots if p.bar_index <= i - 10]
        
        cands = run_setup_detection(window, known_pivots, atr, config, feed, market, trend)
        
        for c in cands:
            pivot_price = c.trigger_pivot.price if c.trigger_pivot else ""
            output.append([
                c.detected_at.isoformat(),
                c.setup_type.name,
                c.direction.name,
                round(c.trigger_price, 2),
                round(pivot_price, 2) if pivot_price else "",
                round(c.stop_price, 2)
            ])
            
    os.makedirs('scratch', exist_ok=True)
    csv_path = 'scratch/btc_setups.csv'
    with open(csv_path, 'w', newline='') as f:
        writer = csv.writer(f)
        writer.writerow(['timestamp', 'setup_type', 'direction', 'trigger_price', 'pivot_price', 'stop_price'])
        writer.writerows(output)
        
    print(f"Done. Wrote {len(output)} setups to {csv_path}")
