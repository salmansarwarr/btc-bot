"""
Pre-tuning investigations:

1. TRAIN clustered PnL concentration by distinct entry timestamp.
2. SR_FLIP-only standalone performance on TRAIN and TEST/OOS.

This script does not change parameters. It uses the fixed walk-forward registry.
"""

from __future__ import annotations

import copy
import os
import sys
from collections import defaultdict
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from bot.structs import SetupType
from walk_forward import WINDOWS, cluster_analysis, run_window


CLUSTER_WINDOW = timedelta(hours=3)


def mark_clustered(trades) -> list:
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
        trade._investigation_clustered = peers > 0
    return [trade for trade in trades if trade._investigation_clustered]


def pnl_usd(trade) -> float:
    return trade.realized_r * trade.initial_risk_usd


def clustered_event_concentration(engine) -> dict:
    trades = engine.trade_journal
    clustered = mark_clustered(trades)
    total_clustered_pnl = sum(pnl_usd(trade) for trade in clustered)

    by_ts = defaultdict(list)
    for trade in clustered:
        by_ts[trade.entry_timestamp].append(trade)

    events = []
    for entry_ts, group in by_ts.items():
        event_pnl = sum(pnl_usd(trade) for trade in group)
        events.append(
            {
                "entry_timestamp": entry_ts,
                "trades": len(group),
                "pnl": event_pnl,
                "setups": sorted({trade.setup_type.name for trade in group if trade.setup_type}),
                "directions": sorted({trade.direction.name for trade in group if trade.direction}),
                "avg_r": sum(trade.realized_r for trade in group) / len(group),
            }
        )

    events.sort(key=lambda row: row["pnl"], reverse=True)

    positive_clustered_pnl = sum(row["pnl"] for row in events if row["pnl"] > 0)
    majority_target = positive_clustered_pnl * 0.5
    cumulative = 0.0
    events_to_majority = 0
    for row in events:
        if row["pnl"] <= 0:
            continue
        cumulative += row["pnl"]
        events_to_majority += 1
        if cumulative >= majority_target:
            break

    return {
        "total_trades": len(trades),
        "clustered_trades": len(clustered),
        "total_pnl": sum(pnl_usd(trade) for trade in trades),
        "clustered_pnl": total_clustered_pnl,
        "positive_clustered_pnl": positive_clustered_pnl,
        "event_count": len(events),
        "positive_event_count": sum(1 for row in events if row["pnl"] > 0),
        "events_to_majority": events_to_majority,
        "majority_pnl": cumulative,
        "events": events,
    }


def summarize_engine(engine) -> dict:
    stats = engine.get_summary_stats()
    return {
        "trades": stats.get("total_trades", 0),
        "wr": stats.get("win_rate", 0.0) * 100,
        "avg_r": stats.get("avg_r", 0.0),
        "max_dd": stats.get("max_drawdown_pct", 0.0),
    }


def patch_sr_flip_only():
    import bot.setup_detection.runner as runner_mod
    import bot.backtesting.engine as engine_mod

    original_runner = runner_mod.run_setup_detection
    original_engine = engine_mod.run_setup_detection

    def sr_flip_only(*args, **kwargs):
        candidates = original_runner(*args, **kwargs)
        return [cand for cand in candidates if cand.setup_type == SetupType.SR_FLIP]

    runner_mod.run_setup_detection = sr_flip_only
    engine_mod.run_setup_detection = sr_flip_only
    return runner_mod, engine_mod, original_runner, original_engine


def run_sr_flip_only(window_key: str):
    runner_mod, engine_mod, original_runner, original_engine = patch_sr_flip_only()
    try:
        return run_window(WINDOWS[window_key])
    finally:
        runner_mod.run_setup_detection = original_runner
        engine_mod.run_setup_detection = original_engine


def print_cluster_report(result: dict) -> None:
    print("\n" + "=" * 78)
    print("CLUSTERED PNL CONCENTRATION - TRAIN")
    print("=" * 78)
    share = (result["clustered_pnl"] / result["total_pnl"] * 100) if result["total_pnl"] else 0.0
    print(f"Total trades:             {result['total_trades']}")
    print(f"Clustered trades:         {result['clustered_trades']}")
    print(f"Distinct clustered events:{result['event_count']:>6}")
    print(f"Positive clustered events:{result['positive_event_count']:>6}")
    print(f"Total PnL:                ${result['total_pnl']:,.0f}")
    print(f"Clustered PnL:            ${result['clustered_pnl']:,.0f} ({share:.1f}% of total)")
    print(
        "Events for 50% of positive clustered PnL: "
        f"{result['events_to_majority']} (${result['majority_pnl']:,.0f})"
    )

    print("\nTop clustered entry-timestamp events by PnL:")
    print(f"{'Entry timestamp':<25} {'n':>3} {'PnL':>12} {'AvgR':>7} {'Dir':<9} Setups")
    print("-" * 78)
    for row in result["events"][:12]:
        ts = row["entry_timestamp"].strftime("%Y-%m-%d %H:%M") if row["entry_timestamp"] else "N/A"
        setups = ",".join(row["setups"])
        dirs = ",".join(row["directions"])
        print(f"{ts:<25} {row['trades']:>3} ${row['pnl']:>10,.0f} {row['avg_r']:>+7.2f} {dirs:<9} {setups}")


def print_sr_report(train: dict, test: dict) -> None:
    print("\n" + "=" * 78)
    print("SR_FLIP ONLY - STANDALONE PERFORMANCE")
    print("=" * 78)
    print(f"{'Split':<10} {'Trades':>7} {'WR':>8} {'AvgR':>8} {'Max DD':>9}")
    print("-" * 48)
    for label, row in (("TRAIN", train), ("TEST/OOS", test)):
        print(
            f"{label:<10} {row['trades']:>7} {row['wr']:>7.2f}% "
            f"{row['avg_r']:>+8.4f} {row['max_dd']:>8.2f}%"
        )


def main() -> None:
    print("=" * 78)
    print("PRE-TUNING INVESTIGATION")
    print("No parameter changes; TEST/OOS is read as a named investigation event.")
    print("=" * 78)

    print("\nRunning TRAIN baseline for clustered-event concentration...")
    train_engine = run_window(WINDOWS["train"])
    cluster_result = clustered_event_concentration(train_engine)
    print_cluster_report(cluster_result)

    print("\nRunning SR_FLIP-only TRAIN...")
    sr_train = summarize_engine(run_sr_flip_only("train"))

    print("\nRunning SR_FLIP-only TEST/OOS...")
    sr_test = summarize_engine(run_sr_flip_only("test"))
    print_sr_report(sr_train, sr_test)


if __name__ == "__main__":
    main()
