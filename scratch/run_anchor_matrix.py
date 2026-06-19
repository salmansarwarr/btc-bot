"""
SR_FLIP anchor matrix.

Protocol:
  1. Run SR_FLIP-only diagnostics on TRAIN.
  2. Run TRAIN-only additive tests: SR_FLIP + one other setup type.
  3. Run TEST/OOS only for up to two preselected finalists.
  4. Do not touch HOLDOUT.

No parameters are modified. Setup isolation is done by filtering detected
candidates before they enter the normal entry/risk/lifecycle pipeline.
"""

from __future__ import annotations

import os
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.structs import AssetConfig, SetupType
from walk_forward import (
    INITIAL_EQUITY,
    WINDOWS,
    build_sorted,
    fetch_bars,
    reset_global_state,
)


CLUSTER_WINDOW = timedelta(hours=3)
ANCHOR = SetupType.SR_FLIP
ADDITIONS = [
    SetupType.CDC,
    SetupType.OPEN_DRIVE,
    SetupType.MSB_DEEP,
    SetupType.MSB_SHALLOW,
    SetupType.MOMENTUM_DIVERGENCE,
    SetupType.CONSOLIDATION_ENTRY,
]


@dataclass(frozen=True)
class WindowBars:
    warmup: list
    real: list


def load_window_bars(window_key: str) -> WindowBars:
    window = WINDOWS[window_key]
    warmup_ms = int(window.warmup_start.timestamp() * 1000)
    end_ms = int(window.end.timestamp() * 1000)

    print(f"\nFetching {window.label} bars once...")
    all_h1 = fetch_bars("BTC/USDT", "1h", warmup_ms, end_ms)
    all_d1 = fetch_bars("BTC/USDT", "1d", warmup_ms, end_ms)
    warmup = build_sorted(
        [bar for bar in all_h1 if bar.timestamp < window.start],
        [bar for bar in all_d1 if bar.timestamp < window.start],
    )
    real = build_sorted(
        [bar for bar in all_h1 if window.start <= bar.timestamp < window.end],
        [bar for bar in all_d1 if window.start <= bar.timestamp < window.end],
    )
    print(f"  H1 bars total: {len(all_h1)}, D1 bars total: {len(all_d1)}")
    print(f"  Warmup bars: {len(warmup)}, {window_key} bars: {len(real)}")
    return WindowBars(warmup=warmup, real=real)


def run_allowed_set(label: str, bars: WindowBars, allowed: set[SetupType]):
    import bot.setup_detection.runner as runner_mod

    original_runner = runner_mod.run_setup_detection

    def filtered_detection(*args, **kwargs):
        candidates = original_runner(*args, **kwargs)
        return [candidate for candidate in candidates if candidate.setup_type in allowed]

    runner_mod.run_setup_detection = filtered_detection
    try:
        reset_global_state()
        from bot.backtesting.engine import BacktestEngine
        from bot.data_ingestion.feed_manager import ExternalFeedState, feeds

        if "BTC" not in feeds:
            feeds["BTC"] = ExternalFeedState(asset="BTC")

        print(f"  Running {label}...")
        warmup_engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
        warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        for bar in bars.warmup:
            warmup_engine.step(bar, oi=0.0, liq=0.0)

        engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
        engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        engine._pending_fills = list(warmup_engine._pending_fills)
        engine._active_setup_keys = set(warmup_engine._active_setup_keys)
        for bar in bars.real:
            engine.step(bar, oi=0.0, liq=0.0)
        return engine
    finally:
        runner_mod.run_setup_detection = original_runner


def pnl_usd(trade) -> float:
    return trade.realized_r * trade.initial_risk_usd


def summarize(label: str, engine, allowed: set[SetupType]) -> dict:
    stats = engine.get_summary_stats()
    trades = engine.trade_journal
    total_pnl = sum(pnl_usd(trade) for trade in trades)
    setup_counts = defaultdict(int)
    setup_pnl = defaultdict(float)
    for trade in trades:
        name = trade.setup_type.name if trade.setup_type else "UNKNOWN"
        setup_counts[name] += 1
        setup_pnl[name] += pnl_usd(trade)

    return {
        "label": label,
        "allowed": "+".join(setup.name for setup in sorted(allowed, key=lambda s: s.name)),
        "engine": engine,
        "trades": stats.get("total_trades", 0),
        "wr": stats.get("win_rate", 0.0) * 100,
        "avg_r": stats.get("avg_r", 0.0),
        "max_dd": stats.get("max_drawdown_pct", 0.0),
        "pnl": total_pnl,
        "setup_counts": dict(setup_counts),
        "setup_pnl": dict(setup_pnl),
    }


def mark_clusters(trades) -> None:
    for trade in trades:
        peers = sum(
            1
            for other in trades
            if other is not trade
            and other.direction == trade.direction
            and trade.entry_timestamp is not None
            and other.entry_timestamp is not None
            and abs(other.entry_timestamp - trade.entry_timestamp) <= CLUSTER_WINDOW
        )
        trade._anchor_clustered = peers > 0


def group_stats(trades, key_fn) -> list[tuple[str, int, float, float, float]]:
    groups = defaultdict(list)
    for trade in trades:
        groups[key_fn(trade)].append(trade)

    rows = []
    for key, group in groups.items():
        n = len(group)
        wins = sum(1 for trade in group if trade.realized_r > 0)
        avg_r = sum(trade.realized_r for trade in group) / n if n else 0.0
        pnl = sum(pnl_usd(trade) for trade in group)
        rows.append((str(key), n, wins / n * 100 if n else 0.0, avg_r, pnl))
    rows.sort(key=lambda row: row[4], reverse=True)
    return rows


def print_group(title: str, rows: list[tuple[str, int, float, float, float]]) -> None:
    print(f"\n{title}")
    print(f"{'Bucket':<18} {'n':>5} {'WR':>8} {'AvgR':>8} {'PnL':>12}")
    print("-" * 56)
    for key, n, wr, avg_r, pnl in rows:
        print(f"{key:<18} {n:>5} {wr:>7.2f}% {avg_r:>+8.3f} ${pnl:>10,.0f}")


def print_sr_diagnostics(sr_row: dict) -> None:
    trades = sr_row["engine"].trade_journal
    mark_clusters(trades)

    print("\n" + "=" * 78)
    print("SR_FLIP TRAIN DIAGNOSTICS")
    print("=" * 78)
    print_summary_table([sr_row], title="SR_FLIP-only TRAIN baseline")
    print_group(
        "Clustered vs isolated",
        group_stats(trades, lambda trade: "clustered" if trade._anchor_clustered else "isolated"),
    )
    print_group("Direction", group_stats(trades, lambda trade: trade.direction.name if trade.direction else "UNKNOWN"))
    print_group(
        "Trend class at entry",
        group_stats(trades, lambda trade: trade.trend_class_at_entry.name if trade.trend_class_at_entry else "UNKNOWN"),
    )
    print_group(
        "HTF bias at entry",
        group_stats(trades, lambda trade: trade.htf_bias_at_entry.name if trade.htf_bias_at_entry else "UNKNOWN"),
    )
    print_group(
        "Entry month",
        group_stats(trades, lambda trade: trade.entry_timestamp.strftime("%Y-%m") if trade.entry_timestamp else "UNKNOWN"),
    )


def print_summary_table(rows: list[dict], title: str) -> None:
    print("\n" + title)
    print(f"{'Label':<24} {'Trades':>7} {'WR':>8} {'AvgR':>8} {'MaxDD':>9} {'PnL':>12}")
    print("-" * 74)
    for row in rows:
        print(
            f"{row['label']:<24} {row['trades']:>7} {row['wr']:>7.2f}% "
            f"{row['avg_r']:>+8.4f} {row['max_dd']:>8.2f}% ${row['pnl']:>10,.0f}"
        )


def select_finalists(sr_row: dict, rows: list[dict]) -> tuple[list[dict], str]:
    dd_limit = sr_row["max_dd"] + 5.0
    passing = [
        row
        for row in rows
        if row["pnl"] > sr_row["pnl"]
        and row["avg_r"] > 0
        and row["max_dd"] <= dd_limit
    ]
    passing.sort(key=lambda row: (row["pnl"], row["avg_r"], -row["max_dd"]), reverse=True)
    if passing:
        return passing[:2], f"passed rule: PnL > SR-only, AvgR > 0, MaxDD <= {dd_limit:.2f}%"

    fallback = [row for row in rows if row["avg_r"] > 0]
    fallback.sort(key=lambda row: (row["avg_r"] * 100 - row["max_dd"], row["pnl"]), reverse=True)
    return fallback[:2], "fallback: no combos passed DD/PnL rule; selected best positive-AvgR score"


def print_marginal_setup_notes(rows: list[dict], title: str) -> None:
    print(f"\n{title}")
    print(f"{'Combo':<24} {'Added n':>8} {'Added PnL':>12}")
    print("-" * 48)
    for row in rows:
        added = [setup for setup in row["setup_counts"] if setup != ANCHOR.name]
        added_n = sum(row["setup_counts"][setup] for setup in added)
        added_pnl = sum(row["setup_pnl"][setup] for setup in added)
        print(f"{row['label']:<24} {added_n:>8} ${added_pnl:>10,.0f}")


def main() -> None:
    print("=" * 78)
    print("SR_FLIP ANCHOR MATRIX")
    print("TRAIN does selection. TEST/OOS only runs selected finalists. HOLDOUT untouched.")
    print("=" * 78)

    train_bars = load_window_bars("train")
    test_bars = load_window_bars("test")

    train_rows = []
    sr_engine = run_allowed_set("TRAIN SR_FLIP", train_bars, {ANCHOR})
    sr_row = summarize("SR_ONLY", sr_engine, {ANCHOR})
    print_sr_diagnostics(sr_row)

    for addition in ADDITIONS:
        allowed = {ANCHOR, addition}
        label = f"SR+{addition.name}"
        engine = run_allowed_set(f"TRAIN {label}", train_bars, allowed)
        train_rows.append(summarize(label, engine, allowed))

    print_summary_table([sr_row] + train_rows, title="TRAIN anchor matrix")
    print_marginal_setup_notes(train_rows, "Marginal added-setup contribution inside each TRAIN combo")

    finalists, reason = select_finalists(sr_row, train_rows)
    print("\nFinalist selection:")
    print(f"  {reason}")
    for row in finalists:
        print(f"  - {row['label']}")

    sr_test_engine = run_allowed_set("TEST/OOS SR_FLIP", test_bars, {ANCHOR})
    sr_test_row = summarize("SR_ONLY", sr_test_engine, {ANCHOR})

    test_rows = []
    for finalist in finalists:
        allowed = {SetupType[name] for name in finalist["allowed"].split("+")}
        engine = run_allowed_set(f"TEST/OOS {finalist['label']}", test_bars, allowed)
        test_rows.append(summarize(finalist["label"], engine, allowed))

    print_summary_table([sr_test_row] + test_rows, title="TEST/OOS SR-only baseline + selected finalists")
    if test_rows:
        print_marginal_setup_notes(test_rows, "Marginal added-setup contribution inside each TEST/OOS combo")
    else:
        print("\nNo finalists selected for TEST/OOS.")


if __name__ == "__main__":
    main()
