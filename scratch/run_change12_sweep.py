"""Change 12 sweep: cluster P&L scaling cap2 vs full vs off (Change 11 baseline).

Fix vs original: reset_global_state() is called before each mode run to clear
all module-level caches (OHLCV buffers, pivot registry, indicator state, feed
manager, HTF bias). Without this, the second and third modes inherit contaminated
state from prior runs, making results non-comparable.

Fix v2 (warmup): after reset, a 30-day warmup pass is run on bars immediately
preceding the test window. This pre-conditions ATR, pivots, HTF bias and
indicator state identically for every mode, so each run starts from the same
warm baseline rather than a cold-start. _pending_fills and _active_setup_keys
are transferred from the warmup engine to the real engine so any setup detected
on the warmup's last bar fills correctly on the first bar of the test window.
"""
from __future__ import annotations

import sys
import csv
import subprocess
import tempfile
import os
from datetime import datetime, timezone, timedelta

sys.path.insert(0, ".")

from bot.config import CONFIG
from bot.structs import AssetConfig, OHLCV_Bar
from run_backtest import fetch_all_bars
from scratch.walk_forward import WINDOWS

# Warmup window: 30 days of H1+D1 bars immediately before the test window.
# Long enough for ATR(14) and pivot registry to stabilise on D1 bars.
WARMUP_DAYS = 30


def reset_global_state():
    """Clear all module-level global state between sweep runs."""
    from bot.data_ingestion import ohlcv_buffer, feed_manager
    from bot.market_context import htf_bias as htf_bias_mod, pivot_registry as pivot_mod
    from bot.indicators import registry as reg_mod

    if hasattr(ohlcv_buffer, "_buffers"):
        ohlcv_buffer._buffers.clear()
    elif hasattr(ohlcv_buffer, "buffers"):
        ohlcv_buffer.buffers.clear()

    if hasattr(feed_manager, "feeds"):
        feed_manager.feeds.clear()

    if hasattr(htf_bias_mod, "htf_bias"):
        htf_bias_mod.htf_bias.clear()

    if hasattr(pivot_mod, "pivot_registry"):
        pivot_mod.pivot_registry.clear()

    if hasattr(reg_mod, "_registry"):
        reg_mod._registry.clear()
    elif hasattr(reg_mod, "registry"):
        reg_mod.registry.clear()


def load_bars(start_ms: int, end_ms: int) -> list:
    h1 = fetch_all_bars("binance", "BTC/USDT", "1h", start_ms, end_ms)
    d1 = fetch_all_bars("binance", "BTC/USDT", "1d", start_ms, end_ms)
    bars = h1 + d1
    bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == "D1" else 0))
    return bars


def run_mode(mode: str, warmup_bars: list, test_bars: list) -> dict:
    # 1. Full state reset
    reset_global_state()

    CONFIG["CLUSTER_PNL_SCALING_MODE"] = mode

    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    from bot.backtesting.engine import BacktestEngine

    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    # 2. Warmup pass — conditions global indicator state (ATR, pivots, HTF bias).
    #    Asset config is registered so setup detection runs and _pending_fills
    #    is populated; this is transferred to the real engine after warmup so
    #    any setup detected on the warmup's last bar fills on the first test bar.
    warmup_engine = BacktestEngine(initial_equity=100_000.0)
    warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    for b in warmup_bars:
        warmup_engine.step(b, oi=0.0, liq=0.0)

    # 3. Real replay — inherits warm global state and pending fills from warmup boundary
    engine = BacktestEngine(initial_equity=100_000.0)
    engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    engine._pending_fills = warmup_engine._pending_fills
    engine._active_setup_keys = warmup_engine._active_setup_keys

    for b in test_bars:
        engine.step(b, oi=0.0, liq=0.0)

    stats = engine.get_summary_stats()
    skipped = stats.get("skipped_reasons", {})
    row = {
        "mode": mode,
        "total_trades": stats["total_trades"],
        "win_rate": stats.get("win_rate", 0.0) * 100,
        "avg_r": stats.get("avg_r", 0.0),
        "max_dd_engine": stats.get("max_drawdown_pct", 0.0),
        "quick_losses": stats.get("quick_losses", 0),
        "heat_cap": skipped.get("HEAT_CAP", 0),
        "md_skip": skipped.get("MD_NO_CLUSTER_PEER", 0),
    }

    # Write journal to temp CSV and run analyze_clusters on it
    fields = [
        "trade_id", "asset", "timeframe", "setup_type", "setup_class",
        "direction", "management_mode", "conviction_score",
        "entry_price", "entry_timestamp", "exit_price", "exit_timestamp",
        "initial_risk_usd", "realized_r", "drawdown_tier_at_entry",
        "cdc_qualifies_zero_tolerance",
    ]
    path = os.path.join(tempfile.gettempdir(), f"change12_{mode}.csv")
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in engine.trade_journal:
            writer.writerow({
                "trade_id": t.trade_id,
                "asset": t.asset,
                "timeframe": t.timeframe,
                "setup_type": t.setup_type.name if t.setup_type else "",
                "setup_class": t.setup_class.name if t.setup_class else "",
                "direction": t.direction.name if t.direction else "",
                "management_mode": t.management_mode.name if t.management_mode else "",
                "conviction_score": t.conviction_score,
                "entry_price": t.entry_price,
                "entry_timestamp": t.entry_timestamp,
                "exit_price": t.exit_price,
                "exit_timestamp": t.exit_timestamp,
                "initial_risk_usd": t.initial_risk_usd,
                "realized_r": t.realized_r,
                "drawdown_tier_at_entry": (
                    t.drawdown_tier_at_entry.name if t.drawdown_tier_at_entry else ""
                ),
                "cdc_qualifies_zero_tolerance": t.cdc_qualifies_zero_tolerance,
            })

    out = subprocess.check_output(
        [sys.executable, "scratch/analyze_clusters.py", path], text=True
    )
    for line in out.splitlines():
        if "Max DD - full journal:" in line:
            row["max_dd_journal"] = float(line.split(":")[1].strip().rstrip("%"))
        elif line.strip().startswith("Isolated:"):
            parts = line.split()
            row["isolated_n"] = int(parts[1])
        elif "isolated share:" in line:
            pct = line.split("(")[1].split("%")[0]
            row["isolated_pnl_pct"] = float(pct)
        elif "Max DD - isolated" in line:
            row["isolated_dd"] = float(line.split(":")[1].split("%")[0].strip())
        elif "Max DD - clustered" in line:
            row["clustered_dd"] = float(line.split(":")[1].split("%")[0].strip())

    return row


def main():
    train_window = WINDOWS["train"]
    test_start   = train_window.start
    test_end     = train_window.end
    warmup_start = test_start - timedelta(days=WARMUP_DAYS)

    print(f"Loading warmup bars ({WARMUP_DAYS}d before test window)...")
    warmup_bars = load_bars(
        int(warmup_start.timestamp() * 1000),
        int(test_start.timestamp() * 1000),
    )
    print(f"  {len(warmup_bars)} warmup bars loaded")

    print("Loading test bars (90d window)...")
    test_bars = load_bars(
        int(test_start.timestamp() * 1000),
        int(test_end.timestamp() * 1000),
    )
    print(f"  {len(test_bars)} test bars loaded\n")

    results = []
    for mode in ("off", "cap2", "full"):
        print(f"Running CLUSTER_PNL_SCALING_MODE={mode!r}  "
              f"(reset → {WARMUP_DAYS}d warmup → 90d replay)...")
        results.append(run_mode(mode, warmup_bars, test_bars))
        r = results[-1]
        print(f"  → {r['total_trades']} trades, WR {r['win_rate']:.2f}%, "
              f"EngDD {r['max_dd_engine']:.2f}%, JnlDD {r.get('max_dd_journal', 0):.2f}%\n")

    baseline = results[0]
    print("=== Change 12 Sweep (reset + 30d warmup before each mode) ===\n")
    print(f"{'Mode':<6} {'Trades':>6} {'WR':>7} {'AvgR':>7} {'EngDD':>7} {'JnlDD':>7} "
          f"{'IsoDD':>7} {'CluDD':>7} {'Quick':>6} {'HEAT':>6} {'MD_SK':>6}")
    print("-" * 85)
    for r in results:
        print(
            f"{r['mode']:<6} {r['total_trades']:>6} {r['win_rate']:>6.2f}% "
            f"{r['avg_r']:>+7.2f} {r['max_dd_engine']:>6.2f}% "
            f"{r.get('max_dd_journal', 0):>6.2f}% {r.get('isolated_dd', 0):>6.2f}% "
            f"{r.get('clustered_dd', 0):>6.2f}% "
            f"{r['quick_losses']:>6} {r['heat_cap']:>6} {r['md_skip']:>6}"
        )

    print("\nDelta vs baseline (off):")
    for r in results[1:]:
        print(
            f"  {r['mode']}: trades {r['total_trades'] - baseline['total_trades']:+d}, "
            f"WR {r['win_rate'] - baseline['win_rate']:+.2f}pp, "
            f"AvgR {r['avg_r'] - baseline['avg_r']:+.2f}, "
            f"EngDD {r['max_dd_engine'] - baseline['max_dd_engine']:+.2f}pp, "
            f"JnlDD {r.get('max_dd_journal', 0) - baseline.get('max_dd_journal', 0):+.2f}pp, "
            f"IsoDD {r.get('isolated_dd', 0) - baseline.get('isolated_dd', 0):+.2f}pp"
        )

    CONFIG["CLUSTER_PNL_SCALING_MODE"] = "full"
    print(f"\nConfig restored to CLUSTER_PNL_SCALING_MODE='full' after sweep.")


if __name__ == "__main__":
    main()
