import os
import csv
import ccxt
import time
from datetime import datetime, timezone, timedelta
from bot.structs import AssetConfig, OHLCV_Bar
from bot.backtesting.engine import BacktestEngine

def fetch_all_bars(exchange_id, symbol, timeframe, start_ms, end_ms, limit=1000):
    exchange_class = getattr(ccxt, exchange_id)
    exchange = exchange_class({'enableRateLimit': True})

    all_bars = []
    since = start_ms

    while since < end_ms:
        try:
            raw = exchange.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not raw:
                break

            for row in raw:
                ts = row[0]
                dt = datetime.fromtimestamp(ts / 1000.0, tz=timezone.utc)
                if ts >= end_ms:
                    continue

                internal_tf = timeframe.upper()
                if internal_tf == "1D": internal_tf = "D1"
                elif internal_tf == "1H": internal_tf = "H1"
                elif internal_tf == "1W": internal_tf = "W1"

                asset = symbol.split('/')[0] if '/' in symbol else symbol

                bar = OHLCV_Bar(
                    timestamp=dt,
                    open=float(row[1]),    # FIXED: row[1] is open
                    high=float(row[2]),    # FIXED: row[2] is high
                    low=float(row[3]),     # FIXED: row[3] is low
                    close=float(row[4]),   # FIXED: row[4] is close
                    volume=float(row[5]),  # FIXED: row[5] is volume
                    timeframe=internal_tf,
                    asset=asset
                )
                all_bars.append(bar)

            since = raw[-1][0] + 1
            time.sleep(exchange.rateLimit / 1000.0)

        except Exception as e:
            print(f"Error fetching: {e}")
            break

    return all_bars
    
def main():
    ASSET = "ETH"  # Change this to run for different assets
    SYMBOL = "ETH/USDT"
    
    print(f"Fetching 3 months of {ASSET} data...")
    now = datetime(2026, 6, 13, tzinfo=timezone.utc)
    three_months_ago = now - timedelta(days=90)

    start_ms = int(three_months_ago.timestamp() * 1000)
    end_ms   = int(now.timestamp() * 1000)

    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    if ASSET not in feeds:
        feeds[ASSET] = ExternalFeedState(asset=ASSET)

    h1_bars = fetch_all_bars('binance', SYMBOL, '1h', start_ms, end_ms)
    d1_bars = fetch_all_bars('binance', SYMBOL, '1d', start_ms, end_ms)
    print(f"Fetched {len(h1_bars)} H1 bars and {len(d1_bars)} D1 bars.")

    all_bars = h1_bars + d1_bars
    all_bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == 'D1' else 0))

    # Warmup: pre-condition indicators over 30d preceding the test window.
    # ATR, pivots, HTF bias and _pending_fills are all transferred to the real
    # engine so bar 1 of the test window starts from a fully warm state.
    WARMUP_DAYS = 30
    warmup_start_ms = int((three_months_ago - timedelta(days=WARMUP_DAYS)).timestamp() * 1000)

    print(f"Fetching {WARMUP_DAYS}d warmup bars...")
    h1_warmup = fetch_all_bars('binance', SYMBOL, '1h', warmup_start_ms, start_ms)
    d1_warmup = fetch_all_bars('binance', SYMBOL, '1d', warmup_start_ms, start_ms)
    warmup_bars = h1_warmup + d1_warmup
    warmup_bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == 'D1' else 0))
    print(f"Fetched {len(warmup_bars)} warmup bars.")

    print("Running warmup pass...")
    warmup_engine = BacktestEngine(initial_equity=100_000.0)
    warmup_engine.add_asset_config(AssetConfig(symbol=ASSET, active_timeframes=["H1", "D1"]))
    for b in warmup_bars:
        warmup_engine.step(b, oi=0.0, liq=0.0)

    print("Initializing BacktestEngine...")
    engine = BacktestEngine(initial_equity=100_000.0)
    engine.add_asset_config(AssetConfig(symbol=ASSET, active_timeframes=["H1", "D1"]))
    # Transfer pending fills and dedup keys from warmup boundary so any setup
    # detected on the warmup's last bar fills correctly on the first test bar.
    engine._pending_fills = warmup_engine._pending_fills
    engine._active_setup_keys = warmup_engine._active_setup_keys

    print("Running backtest...")
    for i, b in enumerate(all_bars):
        if i % 1000 == 0:
            print(f"Processed {i}/{len(all_bars)} bars...")
        engine.step(b, oi=0.0, liq=0.0)

    print("Backtest complete!")

    stats = engine.get_summary_stats()

    print(f"\n--- {ASSET} SUMMARY STATS ---")
    print(f"Total Trades:      {stats['total_trades']}")
    print(f"Win Rate:          {stats.get('win_rate', 0.0) * 100:.2f}%")
    print(f"Average R:         {stats.get('avg_r', 0.0):.2f}")
    print(f"Max Drawdown:      {stats.get('max_drawdown_pct', 0.0):.2f}%")
    print(f"Quick full-stops (≤3 bars): {stats.get('quick_losses', 0)}")

    print("\nWin rate & avg R by setup type:")
    for k, v in stats.get('by_type_wr', {}).items():
        total = v['wins'] + v['losses']
        wr    = v['wins'] / total if total else 0
        avg   = v['total_r'] / total if total else 0
        print(f"  {k:25s} WR: {wr*100:.1f}%  AvgR: {avg:+.2f}  ({total} trades)")

    print("\nSetups Triggered by Type:")
    for k, v in stats.get('trades_by_type', {}).items():
        print(f"  {k}: {v}")

    print("\nSkipped by Reason:")
    for k, v in stats.get('skipped_reasons', {}).items():
        print(f"  {k}: {v}")

    csv_file = f"trade_journal_{ASSET}.csv"
    if engine.trade_journal:
        with open(csv_file, 'w', newline='') as f:
            fields = [
                "trade_id", "asset", "timeframe", "setup_type", "setup_class",
                "direction", "management_mode", "conviction_score",
                "entry_price", "entry_timestamp", "exit_price", "exit_timestamp",
                "initial_risk_usd", "realized_r",
                "drawdown_tier_at_entry", "cdc_qualifies_zero_tolerance",
            ]
            writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
            writer.writeheader()
            for t in engine.trade_journal:
                row = {
                    "trade_id":        t.trade_id,
                    "asset":           t.asset,
                    "timeframe":       t.timeframe,
                    "setup_type":      t.setup_type.name if t.setup_type else "",
                    "setup_class":     t.setup_class.name if t.setup_class else "",
                    "direction":       t.direction.name if t.direction else "",
                    "management_mode": t.management_mode.name if t.management_mode else "",
                    "conviction_score": t.conviction_score,
                    "entry_price":     t.entry_price,
                    "entry_timestamp": t.entry_timestamp,
                    "exit_price":      t.exit_price,
                    "exit_timestamp":  t.exit_timestamp,
                    "initial_risk_usd": t.initial_risk_usd,
                    "realized_r":      t.realized_r,
                    "drawdown_tier_at_entry": t.drawdown_tier_at_entry.name if t.drawdown_tier_at_entry else "",
                    "cdc_qualifies_zero_tolerance": t.cdc_qualifies_zero_tolerance,
                }
                writer.writerow(row)
        print(f"\nFull journal written to {csv_file}")

    print(f"\n--- SAMPLE OF CLOSED TRADES (up to 20) ---")
    for i, t in enumerate(engine.trade_journal[:20]):
        entry_time = t.entry_timestamp.strftime('%Y-%m-%d %H:%M') if t.entry_timestamp else "N/A"
        exit_time  = t.exit_timestamp.strftime('%Y-%m-%d %H:%M') if t.exit_timestamp else "N/A"
        direction  = t.direction.name if t.direction else "UNK"
        setup      = t.setup_type.name if t.setup_type else "UNK"
        print(f"{i+1:2d}. {direction:4s} {setup:20s} | Entry: {entry_time} @ {t.entry_price:.2f} | Exit: {exit_time} @ {t.exit_price:.2f} | R: {t.realized_r:+.2f}")

if __name__ == "__main__":
    main()