import ccxt, math, os, sys
from datetime import datetime, timezone, timedelta

# Make sure we can import bot.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.structs import (
    OHLCV_Bar, AssetConfig, ExternalFeedState, MarketBasket,
    TrendClass, BiasState, PivotFlag, PivotStrength, Direction, TradeState
)
from bot.indicators import core
from bot.setup_detection.runner import run_setup_detection
from bot.entry_risk.entry_gate import evaluate_entry
from bot.trade_management.lifecycle import update_trade

ACCOUNT_EQUITY = 100_000.0
SYMBOL         = "BTC/USDT"
TIMEFRAME      = "1h"
LIMIT          = 720
WARMUP         = 200
PIVOT_N        = 10

TARGET_TIMESTAMPS = {
    "2026-05-26 17:00",
    "2026-05-27 18:00",
    "2026-05-29 18:00"
}

def fetch_bars(symbol, timeframe, limit):
    exchange = ccxt.binance()
    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    out = []
    for b in raw:
        ts = datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc)
        out.append(OHLCV_Bar(ts, b[1], b[2], b[3], b[4], b[5], timeframe, "BTC"))
    return out

def detect_pivots(bars, n=PIVOT_N):
    pivots = []
    for i in range(n, len(bars) - n):
        win = bars[i - n: i + n + 1]
        b   = bars[i]
        if all(x.high <= b.high for x in win):
            pivots.append(PivotFlag("BTC", TIMEFRAME, b.high, Direction.UP, PivotStrength.MAJOR, i, b.timestamp))
        elif all(x.low >= b.low for x in win):
            pivots.append(PivotFlag("BTC", TIMEFRAME, b.low, Direction.DOWN, PivotStrength.MAJOR, i, b.timestamp))
    return pivots

def infer_htf_bias(bars, i):
    closes = [b.close for b in bars[:i + 1]]
    if len(closes) < 60: return BiasState.NEUTRAL
    ema = core.ema(closes, 50)
    if math.isnan(ema[-1]) or math.isnan(ema[-11]): return BiasState.NEUTRAL
    if ema[-1] > ema[-11]: return BiasState.BULLISH
    if ema[-1] < ema[-11]: return BiasState.BEARISH
    return BiasState.NEUTRAL

def infer_trend_class(bars, i):
    closes = [b.close for b in bars[:i + 1]]
    highs  = [b.high  for b in bars[:i + 1]]
    lows   = [b.low   for b in bars[:i + 1]]
    if len(closes) < 30: return TrendClass.TRENDING
    adx_result = core.adx(highs, lows, closes, 14)
    val = adx_result["adx"][-1]
    if math.isnan(val): return TrendClass.TRENDING
    if val > 40: return TrendClass.LOCKOUT_TREND
    if val > 25: return TrendClass.TRENDING
    return TrendClass.RANGING

def asset_24h_change(bars, i):
    now_bar = bars[i]
    target  = now_bar.timestamp - timedelta(hours=24)
    for b in reversed(bars[:i]):
        if b.timestamp <= target:
            if b.close > 0: return (now_bar.close - b.close) / b.close
            break
    return 0.0

if __name__ == "__main__":
    bars = fetch_bars(SYMBOL, TIMEFRAME, LIMIT)
    all_pivots = detect_pivots(bars, PIVOT_N)
    
    config = AssetConfig("BTC")
    feed = ExternalFeedState("BTC")
    market = MarketBasket(btc_eth_avg_24h_change=0.005)

    active_trades = []

    for i in range(WARMUP, len(bars)):
        window = bars[:i + 1]
        bar = bars[i]
        ts_str = bar.timestamp.strftime("%Y-%m-%d %H:%M")
        
        closes = [b.close for b in window]
        highs  = [b.high  for b in window]
        lows   = [b.low   for b in window]
        atr_series = core.atr(highs, lows, closes, 14)
        atr = atr_series[-1]
        if math.isnan(atr) or atr <= 0: continue
        
        # 1. Update any existing active trades first with the newly closed bar
        to_remove = []
        for trade in active_trades:
            events = update_trade(trade, bar.close, i, atr, bar.timestamp)
            for ev in events:
                if ev["action"] != "HOLD":
                    print(f"[{ts_str}] TRADE {trade.id} ({trade.direction.name}): {ev['action']} - {ev['reason']} | price={bar.close:.2f}, size={trade.position_size:.2f}, R={trade.realized_r:.2f}, stop={trade.stop_price:.2f}")
            if not trade.is_open:
                to_remove.append(trade)
                
        for t in to_remove:
            active_trades.remove(t)

        # 2. Setup Detection only if we match our target timestamps
        if ts_str in TARGET_TIMESTAMPS:
            known_pivots = [p for p in all_pivots if p.bar_index <= i - PIVOT_N]
            htf_bias = infer_htf_bias(bars, i)
            trend_class = infer_trend_class(bars, i)
            chg_24h = asset_24h_change(bars, i)

            candidates = run_setup_detection(window, known_pivots, atr, config, feed, market, trend_class)

            for cand in candidates:
                result = evaluate_entry(
                    candidate=cand, htf_bias=htf_bias, trend_class=trend_class,
                    market_basket=market, asset_24h_change=chg_24h,
                    account_equity=ACCOUNT_EQUITY, atr=atr,
                    bars_for_percentile=window[-50:], bar_index=i, now=bar.timestamp
                )
                
                if result.approved:
                    t = result.trade
                    t.id = f"{cand.setup_type.name}_{ts_str}"
                    # Mock FTAs at 1.5R, 3R, 5R
                    r_dist = abs(t.entry_price - t.stop_price)
                    if t.direction == Direction.UP:
                        t.targets = [t.entry_price + (r_dist * 1.5), t.entry_price + (r_dist * 3.0), t.entry_price + (r_dist * 5.0)]
                    else:
                        t.targets = [t.entry_price - (r_dist * 1.5), t.entry_price - (r_dist * 3.0), t.entry_price - (r_dist * 5.0)]
                    
                    active_trades.append(t)
                    print(f"\n========================================================")
                    print(f"[{ts_str}] ENTRY: {t.id} | dir={t.direction.name}, entry={t.entry_price:.2f}, stop={t.stop_price:.2f}, mode={t.management_mode.name}, targets={[round(x,2) for x in t.targets]}")
                    print(f"========================================================")
