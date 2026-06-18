"""MAX_HEAT_PCT sweep (Change 13 candidate).

Sweeps MAX_HEAT_PCT over [0.06, 0.08, 0.10, 0.12] against the Change 12
baseline (CLUSTER_PNL_SCALING_MODE='full'). HEAT_CAP skips collapsed from
248 → 54 after cluster scaling; the 8% ceiling may now be too loose or too
tight. This sweep finds the optimal value.

Infrastructure: reset → 30d warmup → _pending_fills transfer → 90d replay.
Every value runs on identical warm state. Cross-check the 0.08 result against
run_backtest.py to confirm clean isolation before acting on any other value.

IMPORTANT — module-level constant patching:
heat.py imports MAX_HEAT_PCT and MAX_CORRELATED_HEAT_PCT as module-level floats
at import time. Mutating CONFIG["MAX_HEAT_PCT"] alone is insufficient — the
imported constants in heat.py and config.py must also be patched directly.
This script patches all three locations and restores them after the sweep.

CONFIG held constant across all runs:
  MIN_STOP_ATR_MULT=1.2, SFP_WICK_ATR_MULT=1.0,
  MOMENTUM_DIVERGENCE_MIN_STRENGTH=5.0,
  MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER=True,
  CLUSTER_PNL_SCALING_MODE='full'
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
from bot.structs import AssetConfig
from run_backtest import fetch_all_bars

# Import modules whose constants need patching at runtime
import bot.portfolio.heat as heat_mod
import bot.config as cfg_mod

WARMUP_DAYS = 30
SWEEP_VALUES = [0.06, 0.08, 0.10, 0.12]
BASELINE_VALUE = 0.08  # current live value — used for delta reporting


def set_heat_pct(value: float) -> None:
    """Patch MAX_HEAT_PCT and MAX_CORRELATED_HEAT_PCT in all locations."""
    CONFIG["MAX_HEAT_PCT"] = value
    CONFIG["MAX_CORRELATED_HEAT_PCT"] = value
    cfg_mod.MAX_HEAT_PCT = value
    cfg_mod.MAX_CORRELATED_HEAT_PCT = value
    heat_mod.MAX_HEAT_PCT = value
    heat_mod.MAX_CORRELATED_HEAT_PCT = value


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


def write_journal_csv(engine, path: str) -> None:
    fields = [
        "trade_id", "asset", "timeframe", "setup_type", "setup_class",
        "direction", "management_mode", "conviction_score",
        "entry_price", "entry_timestamp", "exit_price", "exit_timestamp",
        "initial_risk_usd", "realized_r", "drawdown_tier_at_entry",
        "cdc_qualifies_zero_tolerance",
    ]
    with open(path, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for t in engine.trade_journal:
            writer.writerow({
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
                "drawdown_tier_at_entry": (
                    t.drawdown_tier_at_entry.name if t.drawdown_tier_at_entry else ""
                ),
                "cdc_qualifies_zero_tolerance": t.cdc_qualifies_zero_tolerance,
            })


def parse_cluster_output(out: str, row: dict) -> None:
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


def run_value(heat_pct: float, warmup_bars: list, test_bars: list) -> dict:
    # 1. Full state reset
    reset_global_state()

    # 2. Patch heat cap in all locations — CONFIG dict, cfg_mod constants, heat_mod constants
    set_heat_pct(heat_pct)
    CONFIG["CLUSTER_PNL_SCALING_MODE"] = "full"

    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    from bot.backtesting.engine import BacktestEngine

    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    # 3. Warmup pass
    warmup_engine = BacktestEngine(initial_equity=100_000.0)
    warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    for b in warmup_bars:
        warmup_engine.step(b, oi=0.0, liq=0.0)

    # 4. Real replay — inherit warm state and boundary pending fills
    engine = BacktestEngine(initial_equity=100_000.0)
    engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    engine._pending_fills = warmup_engine._pending_fills
    engine._active_setup_keys = warmup_engine._active_setup_keys

    for b in test_bars:
        engine.step(b, oi=0.0, liq=0.0)

    stats = engine.get_summary_stats()
    skipped = stats.get("skipped_reasons", {})

    row = {
        "heat_pct":       heat_pct,
        "total_trades":   stats["total_trades"],
        "win_rate":       stats.get("win_rate", 0.0) * 100,
        "avg_r":          stats.get("avg_r", 0.0),
        "max_dd_engine":  stats.get("max_drawdown_pct", 0.0),
        "quick_losses":   stats.get("quick_losses", 0),
        "heat_cap":       skipped.get("HEAT_CAP", 0),
        "md_skip":        skipped.get("MD_NO_CLUSTER_PEER", 0),
        "max_dd_journal": 0.0,
        "isolated_n":     0,
        "isolated_pnl_pct": 0.0,
        "isolated_dd":    0.0,
        "clustered_dd":   0.0,
    }

    # 5. Cluster analysis
    path = os.path.join(tempfile.gettempdir(), f"heat_sweep_{int(heat_pct*100):03d}.csv")
    write_journal_csv(engine, path)
    try:
        out = subprocess.check_output(
            [sys.executable, "scratch/analyze_clusters.py", path], text=True
        )
        parse_cluster_output(out, row)
    except subprocess.CalledProcessError as e:
        print(f"  [warn] analyze_clusters failed for {heat_pct}: {e}")

    return row


def print_table(results: list, baseline_row: dict) -> None:
    print(
        f"\n=== MAX_HEAT_PCT Sweep "
        f"(reset + {WARMUP_DAYS}d warmup, CLUSTER_PNL_SCALING_MODE='full') ===\n"
    )
    hdr = (
        f"{'HEAT':>6} {'Trades':>6} {'WR':>7} {'AvgR':>7} "
        f"{'EngDD':>7} {'JnlDD':>7} {'IsoDD':>7} {'CluDD':>7} "
        f"{'Quick':>6} {'HEAT_SK':>8} {'MD_SK':>6}"
    )
    print(hdr)
    print("-" * len(hdr))
    for r in results:
        marker = " ◄ baseline" if r["heat_pct"] == BASELINE_VALUE else ""
        print(
            f"{r['heat_pct']:>5.0%}  {r['total_trades']:>6}  {r['win_rate']:>6.2f}%"
            f"  {r['avg_r']:>+6.2f}  {r['max_dd_engine']:>6.2f}%"
            f"  {r.get('max_dd_journal', 0):>6.2f}%  {r.get('isolated_dd', 0):>6.2f}%"
            f"  {r.get('clustered_dd', 0):>6.2f}%"
            f"  {r['quick_losses']:>6}  {r['heat_cap']:>8}  {r['md_skip']:>6}{marker}"
        )

    print(f"\nDelta vs baseline ({BASELINE_VALUE:.0%}):")
    for r in results:
        if r["heat_pct"] == BASELINE_VALUE:
            continue
        print(
            f"  {r['heat_pct']:.0%}: "
            f"trades {r['total_trades'] - baseline_row['total_trades']:+d}, "
            f"WR {r['win_rate'] - baseline_row['win_rate']:+.2f}pp, "
            f"AvgR {r['avg_r'] - baseline_row['avg_r']:+.2f}, "
            f"EngDD {r['max_dd_engine'] - baseline_row['max_dd_engine']:+.2f}pp, "
            f"JnlDD {r.get('max_dd_journal', 0) - baseline_row.get('max_dd_journal', 0):+.2f}pp, "
            f"IsoDD {r.get('isolated_dd', 0) - baseline_row.get('isolated_dd', 0):+.2f}pp, "
            f"HEAT_SK {r['heat_cap'] - baseline_row['heat_cap']:+d}"
        )


def main():
    test_end     = datetime(2026, 6, 13, tzinfo=timezone.utc)
    test_start   = test_end - timedelta(days=90)
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
    for heat_pct in SWEEP_VALUES:
        print(
            f"Running MAX_HEAT_PCT={heat_pct:.0%}  "
            f"(reset → {WARMUP_DAYS}d warmup → 90d replay)..."
        )
        r = run_value(heat_pct, warmup_bars, test_bars)
        results.append(r)
        print(
            f"  → {r['total_trades']} trades, WR {r['win_rate']:.2f}%, "
            f"EngDD {r['max_dd_engine']:.2f}%, JnlDD {r.get('max_dd_journal', 0):.2f}%\n"
        )

    baseline_row = next(r for r in results if r["heat_pct"] == BASELINE_VALUE)
    print_table(results, baseline_row)

    # Restore all locations to live values
    set_heat_pct(BASELINE_VALUE)
    CONFIG["CLUSTER_PNL_SCALING_MODE"] = "full"
    print(f"\nConfig restored to MAX_HEAT_PCT={BASELINE_VALUE:.0%} after sweep.")


if __name__ == "__main__":
    main()