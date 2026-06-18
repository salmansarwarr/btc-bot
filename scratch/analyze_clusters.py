"""
analyze_clusters.py — Cluster concentration analysis for trade_journal.csv

Usage: python3 analyze_clusters.py [path/to/trade_journal.csv]

Marks each trade as "clustered" if another trade in the same direction and
timeframe entered within ±CLUSTER_WINDOW_BARS bars of it, then compares
max drawdown contribution from clustered vs isolated trades.
"""
import csv
import sys
from datetime import datetime, timedelta

CLUSTER_WINDOW_BARS = 3
BAR_HOURS = {"H1": 1, "D1": 24}
INITIAL_EQUITY = 100000.0


def parse_ts(s):
    return datetime.fromisoformat(s)


def load_trades(path):
    trades = []
    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            row["entry_timestamp"] = parse_ts(row["entry_timestamp"])
            row["exit_timestamp"] = parse_ts(row["exit_timestamp"])
            row["realized_r"] = float(row["realized_r"])
            row["initial_risk_usd"] = float(row["initial_risk_usd"])
            row["pnl_usd"] = row["realized_r"] * row["initial_risk_usd"]
            trades.append(row)
    return trades


def mark_clusters(trades):
    for t in trades:
        window = timedelta(hours=BAR_HOURS.get(t["timeframe"], 1) * CLUSTER_WINDOW_BARS)
        peers = 0
        for o in trades:
            if o is t:
                continue
            if o["direction"] != t["direction"] or o["timeframe"] != t["timeframe"]:
                continue
            if abs(o["entry_timestamp"] - t["entry_timestamp"]) <= window:
                peers += 1
        t["cluster_peers"] = peers
        t["clustered"] = peers > 0
    return trades


def max_drawdown(trades, initial_equity=INITIAL_EQUITY):
    ordered = sorted(trades, key=lambda t: t["exit_timestamp"])
    equity = initial_equity
    peak = initial_equity
    max_dd = 0.0
    for t in ordered:
        equity += t["pnl_usd"]
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak)
    return max_dd, equity


def print_isolated_by_setup(isolated):
    """Per-setup breakdown within the isolated bucket."""
    by_setup: dict[str, list] = {}
    for t in isolated:
        by_setup.setdefault(t["setup_type"], []).append(t)

    print()
    print("Isolated trades by setup_type:")
    print(f"{'Setup Type':<25} {'n':>4} {'WR':>7} {'AvgR':>8} {'PnL ($)':>12}")
    print("-" * 60)

    rows = []
    for setup_type, group in by_setup.items():
        n = len(group)
        wins = sum(1 for t in group if t["realized_r"] > 0)
        wr = wins / n if n else 0.0
        avg_r = sum(t["realized_r"] for t in group) / n if n else 0.0
        pnl = sum(t["pnl_usd"] for t in group)
        rows.append((setup_type, n, wr, avg_r, pnl))

    rows.sort(key=lambda r: r[4])  # worst PnL first
    for setup_type, n, wr, avg_r, pnl in rows:
        print(f"{setup_type:<25} {n:>4} {wr*100:>6.1f}% {avg_r:>+8.2f} {pnl:>12,.2f}")


def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "trade_journal.csv"
    trades = load_trades(path)
    mark_clusters(trades)

    clustered = [t for t in trades if t["clustered"]]
    isolated = [t for t in trades if not t["clustered"]]

    total_pnl = sum(t["pnl_usd"] for t in trades)
    clustered_pnl = sum(t["pnl_usd"] for t in clustered)
    isolated_pnl = sum(t["pnl_usd"] for t in isolated)

    base_dd, _ = max_drawdown(trades)
    clu_dd, _ = max_drawdown(clustered)
    iso_dd, _ = max_drawdown(isolated)

    print(f"Total trades:      {len(trades)}")
    print(f"Clustered:         {len(clustered)} ({len(clustered)/len(trades)*100:.1f}%)")
    print(f"Isolated:          {len(isolated)} ({len(isolated)/len(trades)*100:.1f}%)")
    print()
    print(f"Total PnL ($):     {total_pnl:,.2f}")
    print(f"  clustered share: {clustered_pnl:,.2f} ({clustered_pnl/total_pnl*100:.1f}%)")
    print(f"  isolated share:  {isolated_pnl:,.2f} ({isolated_pnl/total_pnl*100:.1f}%)")
    print()
    print(f"Max DD - full journal:           {base_dd*100:.2f}%")
    print(f"Max DD - clustered trades only:  {clu_dd*100:.2f}%  (n={len(clustered)})")
    print(f"Max DD - isolated trades only:   {iso_dd*100:.2f}%  (n={len(isolated)})")

    print_isolated_by_setup(isolated)


if __name__ == "__main__":
    main()