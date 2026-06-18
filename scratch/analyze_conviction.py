"""
scratch/analyze_conviction.py — Conviction score breakdown vs performance

Usage: python3 scratch/analyze_conviction.py [path/to/trade_journal.csv]
"""
import csv, sys
from collections import defaultdict

def main():
    path = sys.argv[1] if len(sys.argv) > 1 else "trade_journal.csv"

    by_score = defaultdict(lambda: {"wins": 0, "losses": 0, "total_r": 0.0,
                                     "quick_stops": 0, "pnl": 0.0})

    with open(path, newline="") as f:
        for row in csv.DictReader(f):
            score = int(float(row.get("conviction_score", 0)))
            r     = float(row["realized_r"])
            risk  = float(row["initial_risk_usd"])
            quick = row.get("bars_held", None)  # may not be in journal
            b     = by_score[score]
            b["total_r"]  += r
            b["pnl"]      += r * risk
            b["wins"]      += 1 if r > 0 else 0
            b["losses"]    += 1 if r <= 0 else 0

    print(f"{'Score':>6} {'Trades':>7} {'WR':>7} {'AvgR':>7} {'PnL$':>10}")
    print("-" * 45)
    for score in sorted(by_score):
        b = by_score[score]
        n = b["wins"] + b["losses"]
        wr = b["wins"] / n if n else 0
        avg_r = b["total_r"] / n if n else 0
        print(f"{score:>6} {n:>7} {wr*100:>6.1f}% {avg_r:>+7.2f} {b['pnl']:>10,.0f}")

if __name__ == "__main__":
    main()