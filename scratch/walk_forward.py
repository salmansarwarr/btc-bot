"""
Fixed walk-forward split registry and reporting harness.

Protocol:
  - Tune only on TRAIN.
  - Run TEST/OOS only once per major tuning milestone.
  - Run HOLDOUT only once, as final validation before paper trading.

The current split keeps the existing Change 21 in-sample window as TRAIN and
the already-run OOS window as TEST. Because the most recent 90 days have
already been used for tuning, HOLDOUT is the untouched 90-day block before TEST.
"""

from __future__ import annotations

import argparse
import importlib
import os
import sys
import time
from collections import defaultdict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

import ccxt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.structs import AssetConfig, OHLCV_Bar


WARMUP_DAYS = 30
INITIAL_EQUITY = 100_000.0


@dataclass(frozen=True)
class WalkForwardWindow:
    key: str
    label: str
    start: datetime
    end: datetime
    purpose: str
    guard: str

    @property
    def warmup_start(self) -> datetime:
        return self.start - timedelta(days=WARMUP_DAYS)

    @property
    def days(self) -> int:
        return (self.end - self.start).days


TRAIN_START = datetime(2026, 3, 15, tzinfo=timezone.utc)
TRAIN_END = datetime(2026, 6, 13, tzinfo=timezone.utc)
TEST_START = datetime(2025, 12, 14, tzinfo=timezone.utc)
TEST_END = datetime(2026, 3, 14, tzinfo=timezone.utc)
HOLDOUT_START = datetime(2025, 9, 15, tzinfo=timezone.utc)
HOLDOUT_END = datetime(2025, 12, 14, tzinfo=timezone.utc)

WINDOWS = {
    "train": WalkForwardWindow(
        key="train",
        label="TRAIN / IN-SAMPLE",
        start=TRAIN_START,
        end=TRAIN_END,
        purpose="Only window allowed for iterative parameter tuning and sweeps.",
        guard="open",
    ),
    "test": WalkForwardWindow(
        key="test",
        label="TEST / OOS",
        start=TEST_START,
        end=TEST_END,
        purpose="Touched once per major tuning milestone to check generalization.",
        guard="milestone",
    ),
    "holdout": WalkForwardWindow(
        key="holdout",
        label="FINAL HOLDOUT",
        start=HOLDOUT_START,
        end=HOLDOUT_END,
        purpose="Completely untouched final validation before paper trading.",
        guard="final",
    ),
}


FOCUS_SETUPS = [
    "CDC",
    "OPEN_DRIVE",
    "SR_FLIP",
    "MSB_DEEP",
    "MSB_SHALLOW",
    "MOMENTUM_DIVERGENCE",
    "CONSOLIDATION_ENTRY",
]


def list_windows() -> None:
    print("WALK-FORWARD WINDOWS")
    print("=" * 72)
    for key in ("train", "test", "holdout"):
        w = WINDOWS[key]
        print(f"{key:<8} {w.label:<18} {w.start.date()} -> {w.end.date()}  ({w.days} days)")
        print(f"         Warmup: {w.warmup_start.date()} -> {w.start.date()}  ({WARMUP_DAYS} days)")
        print(f"         Use: {w.purpose}")
    print()
    print("Default command for tuning runs:")
    print("  python3 scratch/walk_forward.py --split train")
    print()
    print("Guarded validation commands:")
    print("  python3 scratch/walk_forward.py --split test --milestone \"Change XX\"")
    print("  python3 scratch/walk_forward.py --split holdout --final-validation --milestone \"pre-paper\"")


def enforce_guard(window: WalkForwardWindow, args: argparse.Namespace) -> None:
    if window.guard == "open":
        return
    if window.guard == "milestone" and args.milestone:
        return
    if window.guard == "final" and args.final_validation and args.milestone:
        return

    if window.guard == "milestone":
        raise SystemExit(
            "Refusing to touch TEST/OOS without an explicit milestone. "
            "Use: --split test --milestone \"Change XX\""
        )
    raise SystemExit(
        "Refusing to touch HOLDOUT before final validation. "
        "Use: --split holdout --final-validation --milestone \"pre-paper\""
    )


def fetch_bars(symbol: str, timeframe: str, start_ms: int, end_ms: int, limit: int = 1000) -> list[OHLCV_Bar]:
    ex = ccxt.binance({"enableRateLimit": True})
    bars: list[OHLCV_Bar] = []
    since = start_ms
    tf_map = {"1h": "H1", "1d": "D1"}
    asset = symbol.split("/")[0]

    while since < end_ms:
        try:
            raw = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not raw:
                break
            for row in raw:
                ts = row[0]
                if ts >= end_ms:
                    continue
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                bars.append(
                    OHLCV_Bar(
                        timestamp=dt,
                        open=float(row[1]),
                        high=float(row[2]),
                        low=float(row[3]),
                        close=float(row[4]),
                        volume=float(row[5]),
                        timeframe=tf_map.get(timeframe, timeframe),
                        asset=asset,
                    )
                )
            since = raw[-1][0] + 1
            time.sleep(ex.rateLimit / 1000)
        except Exception as exc:
            print(f"  fetch error: {exc}")
            break
    return bars


def build_sorted(h1: list[OHLCV_Bar], d1: list[OHLCV_Bar]) -> list[OHLCV_Bar]:
    bars = h1 + d1
    bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == "D1" else 0))
    return bars


def reset_global_state() -> None:
    mods = [
        "bot.market_context.pivot_registry",
        "bot.market_context.htf_bias",
        "bot.indicators.registry",
        "bot.data_ingestion.ohlcv_buffer",
        "bot.data_ingestion.feed_manager",
        "bot.portfolio.heat",
        "bot.portfolio.drawdown",
        "bot.portfolio.ath_realization",
        "bot.portfolio.capitulation",
        "bot.backtesting.engine",
    ]
    for mod in mods:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])


def run_window(window: WalkForwardWindow):
    warmup_ms = int(window.warmup_start.timestamp() * 1000)
    start_ms = int(window.start.timestamp() * 1000)
    end_ms = int(window.end.timestamp() * 1000)

    print("\nFetching data...")
    all_h1 = fetch_bars("BTC/USDT", "1h", warmup_ms, end_ms)
    all_d1 = fetch_bars("BTC/USDT", "1d", warmup_ms, end_ms)
    print(f"  H1 bars total: {len(all_h1)}, D1 bars total: {len(all_d1)}")

    warmup_bars = build_sorted(
        [b for b in all_h1 if b.timestamp < window.start],
        [b for b in all_d1 if b.timestamp < window.start],
    )
    test_bars = build_sorted(
        [b for b in all_h1 if window.start <= b.timestamp < window.end],
        [b for b in all_d1 if window.start <= b.timestamp < window.end],
    )
    print(f"  Warmup bars: {len(warmup_bars)}, {window.key} bars: {len(test_bars)}")

    reset_global_state()

    from bot.backtesting.engine import BacktestEngine
    from bot.data_ingestion.feed_manager import ExternalFeedState, feeds

    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    print("\nRunning warmup pass...")
    warmup_engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
    warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    for bar in warmup_bars:
        warmup_engine.step(bar, oi=0.0, liq=0.0)
    print("Warmup complete.")

    print(f"Running {window.key.upper()} pass...")
    engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
    engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    engine._pending_fills = list(warmup_engine._pending_fills)
    engine._active_setup_keys = set(warmup_engine._active_setup_keys)
    for bar in test_bars:
        engine.step(bar, oi=0.0, liq=0.0)
    print(f"{window.key.upper()} pass complete.\n")
    return engine


def cluster_analysis(trades, initial_equity: float = INITIAL_EQUITY) -> dict:
    window = timedelta(hours=3)

    for trade in trades:
        peers = sum(
            1
            for other in trades
            if other is not trade
            and other.direction == trade.direction
            and trade.entry_timestamp is not None
            and other.entry_timestamp is not None
            and abs(other.entry_timestamp - trade.entry_timestamp) <= window
        )
        trade._wf_clustered = peers > 0

    clustered = [trade for trade in trades if trade._wf_clustered]
    isolated = [trade for trade in trades if not trade._wf_clustered]

    def max_dd_and_pnl(subset):
        if not subset:
            return 0.0, 0.0
        ordered = sorted(subset, key=lambda t: t.exit_timestamp or t.entry_timestamp)
        eq = initial_equity
        peak = initial_equity
        dd = 0.0
        total_pnl = 0.0
        for trade in ordered:
            pnl = trade.realized_r * trade.initial_risk_usd
            eq += pnl
            total_pnl += pnl
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak)
        return dd * 100, total_pnl

    total_pnl = sum(trade.realized_r * trade.initial_risk_usd for trade in trades)
    clustered_dd, clustered_pnl = max_dd_and_pnl(clustered)
    isolated_dd, isolated_pnl = max_dd_and_pnl(isolated)

    return {
        "total_pnl": total_pnl,
        "clustered_n": len(clustered),
        "clustered_pct": len(clustered) / len(trades) * 100 if trades else 0.0,
        "clustered_dd": clustered_dd,
        "clustered_pnl_share": clustered_pnl / total_pnl * 100 if total_pnl else 0.0,
        "isolated_n": len(isolated),
        "isolated_pct": len(isolated) / len(trades) * 100 if trades else 0.0,
        "isolated_dd": isolated_dd,
        "isolated_pnl_share": isolated_pnl / total_pnl * 100 if total_pnl else 0.0,
    }


def per_setup_stats(by_type_wr: dict) -> dict:
    rows = {}
    for name, data in by_type_wr.items():
        n = data.get("wins", 0) + data.get("losses", 0)
        if n == 0:
            continue
        rows[name] = {
            "n": n,
            "wr": data["wins"] / n,
            "avg_r": data["total_r"] / n,
        }
    return rows


def print_report(window: WalkForwardWindow, engine, milestone: str | None) -> None:
    stats = engine.get_summary_stats()
    trades = engine.trade_journal
    skips = stats.get("skipped_reasons", {})
    by_type = stats.get("by_type_wr", {})

    total = stats.get("total_trades", 0)
    quick_stops = stats.get("quick_losses", 0)
    heat_skips = skips.get("HEAT_CAP", 0) + skips.get("CORRELATED_HEAT_CAP", 0)

    print("-" * 70)
    print(f"SUMMARY STATS - {window.label}")
    print("-" * 70)
    print(f"  Total Trades       : {total}")
    print(f"  Win Rate           : {stats.get('win_rate', 0.0) * 100:.2f}%")
    print(f"  Average R          : {stats.get('avg_r', 0.0):+.4f}")
    print(f"  Engine Max DD      : {stats.get('max_drawdown_pct', 0.0):.2f}%")
    if total:
        print(f"  Quick full-stops   : {quick_stops} ({quick_stops / total * 100:.1f}% of trades)")
    print(f"  HEAT_CAP skips     : {heat_skips}")

    print()
    print("-" * 70)
    print("CLUSTER ANALYSIS")
    print("-" * 70)
    if trades:
        ca = cluster_analysis(trades)
        print(f"  {'Segment':<14} {'Trades':>7} {'Share':>7} {'Max DD':>8} {'PnL share':>10}")
        print(f"  {'-' * 50}")
        print(
            f"  {'Clustered':<14} {ca['clustered_n']:>7} {ca['clustered_pct']:>6.1f}%"
            f" {ca['clustered_dd']:>7.2f}% {ca['clustered_pnl_share']:>9.1f}%"
        )
        print(
            f"  {'Isolated':<14} {ca['isolated_n']:>7} {ca['isolated_pct']:>6.1f}%"
            f" {ca['isolated_dd']:>7.2f}% {ca['isolated_pnl_share']:>9.1f}%"
        )
        print(f"\n  Total PnL: ${ca['total_pnl']:,.0f}")
    else:
        print("  No closed trades.")

    print()
    print("-" * 70)
    print(f"PER-SETUP BREAKDOWN - {window.label}")
    print("-" * 70)
    setups = per_setup_stats(by_type)
    print(f"  {'Setup Type':<25} {'n':>4} {'WR':>7} {'AvgR':>7}")
    print(f"  {'-' * 47}")
    for name in FOCUS_SETUPS:
        setup = setups.get(name)
        if not setup:
            print(f"  {name:<25} {'-':>4}")
            continue
        print(f"  {name:<25} {setup['n']:>4} {setup['wr'] * 100:>6.1f}% {setup['avg_r']:>+7.3f}")

    others = {key: value for key, value in setups.items() if key not in FOCUS_SETUPS}
    for name, setup in others.items():
        print(f"  {name:<25} {setup['n']:>4} {setup['wr'] * 100:>6.1f}% {setup['avg_r']:>+7.3f}")

    print()
    print("-" * 70)
    print("SKIPPED REASONS")
    print("-" * 70)
    for reason, count in skips.items():
        print(f"  {reason:<35} {count}")

    print()
    print("=" * 70)
    suffix = f" ({milestone})" if milestone else ""
    print(f"END OF {window.label} REPORT{suffix}")
    print("=" * 70)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run fixed walk-forward train/test/holdout windows.")
    parser.add_argument("--split", choices=WINDOWS.keys(), default="train")
    parser.add_argument("--milestone", help="Required when touching TEST/OOS or HOLDOUT.")
    parser.add_argument("--final-validation", action="store_true", help="Required for HOLDOUT.")
    parser.add_argument("--list", action="store_true", help="Print the split registry and exit.")
    args = parser.parse_args()

    if args.list:
        list_windows()
        return

    window = WINDOWS[args.split]
    enforce_guard(window, args)

    print("=" * 70)
    print("WALK-FORWARD VALIDATION")
    print(f"Split  : {window.label}")
    print(f"Window : {window.start.date()} -> {window.end.date()} ({window.days} days)")
    print(f"Warmup : {window.warmup_start.date()} -> {window.start.date()} ({WARMUP_DAYS} days)")
    print(f"Policy : {window.purpose}")
    print("Config : current working tree parameters; no script-level tuning")
    if args.milestone:
        print(f"Event  : {args.milestone}")
    print("=" * 70)

    engine = run_window(window)
    print_report(window, engine, args.milestone)


if __name__ == "__main__":
    main()
