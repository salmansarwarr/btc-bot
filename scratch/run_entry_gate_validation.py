"""
run_entry_gate_validation.py
============================
Runs the full detection → evaluate_entry pipeline on 30 days of BTC 1H data
and writes a rich CSV for manual chart cross-reference.

Columns:
  timestamp, setup_type, direction,
  trigger_price, pivot_price, stop_price,
  stop_distance_pct, stop_distance_atr,
  conviction, management_mode,
  size_units, size_usd_at_risk,
  r_multiple_to_pivot, htf_bias, trend_class,
  filter_result   (APPROVED / PENDING_FTA / SKIPPED:<reason>)
"""
import ccxt, csv, math, os, sys
from datetime import datetime, timezone, timedelta

# Make sure we can import bot.*
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.structs import (
    OHLCV_Bar, AssetConfig, ExternalFeedState, MarketBasket,
    TrendClass, BiasState, PivotFlag, PivotStrength, Direction,
)
from bot.indicators import core
from bot.setup_detection.runner import run_setup_detection
from bot.entry_risk.entry_gate import evaluate_entry

# ── Constants ─────────────────────────────────────────────────────────────────
ACCOUNT_EQUITY = 100_000.0    # synthetic $100k account for sizing display
SYMBOL         = "BTC/USDT"
TIMEFRAME      = "1h"
LIMIT          = 720          # 30 days
WARMUP         = 200          # bars before we start evaluating
PIVOT_N        = 10           # fractal N for major pivots

# ── Helpers ───────────────────────────────────────────────────────────────────

def fetch_bars(symbol, timeframe, limit):
    exchange = ccxt.binance()
    raw = exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
    out = []
    for b in raw:
        ts = datetime.fromtimestamp(b[0] / 1000, tz=timezone.utc)
        out.append(OHLCV_Bar(ts, b[1], b[2], b[3], b[4], b[5], timeframe, "BTC"))
    return out


def detect_pivots(bars, n=PIVOT_N):
    """Simple N-bar fractal detector.  Returns all pivots regardless of bar."""
    pivots = []
    for i in range(n, len(bars) - n):
        win = bars[i - n: i + n + 1]
        b   = bars[i]
        if all(x.high <= b.high for x in win):
            pivots.append(PivotFlag("BTC", TIMEFRAME, b.high,
                                     Direction.UP, PivotStrength.MAJOR,
                                     i, b.timestamp))
        elif all(x.low >= b.low for x in win):
            pivots.append(PivotFlag("BTC", TIMEFRAME, b.low,
                                     Direction.DOWN, PivotStrength.MAJOR,
                                     i, b.timestamp))
    return pivots


def infer_htf_bias(bars, i):
    """
    Very lightweight proxy: compare close to EMA-50 slope over last 10 bars.
    Returns BiasState.BULLISH / BEARISH / NEUTRAL.
    """
    closes = [b.close for b in bars[:i + 1]]
    if len(closes) < 60:
        return BiasState.NEUTRAL
    ema = core.ema(closes, 50)
    if math.isnan(ema[-1]) or math.isnan(ema[-11]):
        return BiasState.NEUTRAL
    if ema[-1] > ema[-11]:
        return BiasState.BULLISH
    if ema[-1] < ema[-11]:
        return BiasState.BEARISH
    return BiasState.NEUTRAL


def infer_trend_class(bars, i):
    """
    Simple proxy: ADX > 25 → TRENDING; > 40 → LOCKOUT_TREND; else RANGING.
    Falls back to TRENDING when data is insufficient.
    """
    closes = [b.close for b in bars[:i + 1]]
    highs  = [b.high  for b in bars[:i + 1]]
    lows   = [b.low   for b in bars[:i + 1]]
    if len(closes) < 30:
        return TrendClass.TRENDING
    adx_result = core.adx(highs, lows, closes, 14)
    val = adx_result["adx"][-1]
    if math.isnan(val):
        return TrendClass.TRENDING
    if val > 40:
        return TrendClass.LOCKOUT_TREND
    if val > 25:
        return TrendClass.TRENDING
    return TrendClass.RANGING


def asset_24h_change(bars, i):
    """Fraction change of current close vs close ~24 bars ago."""
    now_bar = bars[i]
    target  = now_bar.timestamp - timedelta(hours=24)
    for b in reversed(bars[:i]):
        if b.timestamp <= target:
            if b.close > 0:
                return (now_bar.close - b.close) / b.close
            break
    return 0.0


# ── Main ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    print("Fetching BTC 1H data …")
    bars = fetch_bars(SYMBOL, TIMEFRAME, LIMIT)
    print(f"  {len(bars)} bars from {bars[0].timestamp:%Y-%m-%d} to {bars[-1].timestamp:%Y-%m-%d}")

    all_pivots = detect_pivots(bars, PIVOT_N)
    print(f"  {len(all_pivots)} major pivots detected")

    config  = AssetConfig("BTC")
    feed    = ExternalFeedState("BTC")
    # Neutral market basket so RS filter never fires (conservative default for review)
    market  = MarketBasket(btc_eth_avg_24h_change=0.005)

    rows = []

    print(f"Evaluating bars {WARMUP}…{len(bars)-1} …")
    for i in range(WARMUP, len(bars)):
        window = bars[:i + 1]
        bar    = bars[i]

        closes = [b.close for b in window]
        highs  = [b.high  for b in window]
        lows   = [b.low   for b in window]

        atr_series = core.atr(highs, lows, closes, 14)
        atr = atr_series[-1]
        if math.isnan(atr) or atr <= 0:
            continue

        known_pivots = [p for p in all_pivots if p.bar_index <= i - PIVOT_N]
        htf_bias     = infer_htf_bias(bars, i)
        trend_class  = infer_trend_class(bars, i)
        chg_24h      = asset_24h_change(bars, i)

        candidates = run_setup_detection(
            window, known_pivots, atr, config, feed, market, trend_class
        )

        for cand in candidates:
            result = evaluate_entry(
                candidate        = cand,
                htf_bias         = htf_bias,
                trend_class      = trend_class,
                market_basket    = market,
                asset_24h_change = chg_24h,
                account_equity   = ACCOUNT_EQUITY,
                atr              = atr,
                bars_for_percentile = window[-50:],
                bar_index        = i,
                now              = bar.timestamp,
            )

            # Determine filter_result label
            if result.approved:
                t = result.trade
                filter_label    = "APPROVED"
                stop_out        = t.stop_price
                size_units      = t.position_size
                risk_usd        = t.initial_risk_usd
                mode            = t.management_mode.name
            elif result.needs_fta:
                filter_label    = "PENDING_FTA"
                stop_out        = cand.stop_price
                size_units      = 0.0
                risk_usd        = 0.0
                mode            = (cand.management_mode.name
                                   if cand.management_mode else "—")
            else:
                filter_label    = f"SKIPPED:{result.skipped.reason}"
                stop_out        = cand.stop_price
                size_units      = 0.0
                risk_usd        = 0.0
                mode            = (cand.management_mode.name
                                   if cand.management_mode else "—")

            entry  = cand.trigger_price
            pivot_p = cand.trigger_pivot.price if cand.trigger_pivot else ""

            stop_dist_pct = (abs(entry - stop_out) / entry * 100) if entry else 0
            stop_dist_atr = (abs(entry - stop_out) / atr) if atr else 0

            # R-multiple: distance from entry to pivot (approximate first target)
            if pivot_p != "" and abs(entry - stop_out) > 0:
                r_to_pivot = abs(entry - pivot_p) / abs(entry - stop_out)
            else:
                r_to_pivot = ""

            rows.append({
                "timestamp":         bar.timestamp.strftime("%Y-%m-%d %H:%M"),
                "setup_type":        cand.setup_type.name,
                "direction":         cand.direction.name,
                "trigger_price":     round(entry, 2),
                "pivot_price":       round(pivot_p, 2) if pivot_p != "" else "",
                "stop_price":        round(stop_out, 2),
                "stop_dist_pct":     round(stop_dist_pct, 3),
                "stop_dist_atr":     round(stop_dist_atr, 3),
                "conviction":        cand.conviction_score,
                "management_mode":   mode,
                "size_units":        round(size_units, 6),
                "size_usd_at_risk":  round(risk_usd, 2),
                "r_to_pivot":        round(r_to_pivot, 2) if r_to_pivot != "" else "",
                "htf_bias":          htf_bias.name,
                "trend_class":       trend_class.name,
                "filter_result":     filter_label,
            })

    os.makedirs("scratch", exist_ok=True)
    out_path = "scratch/btc_entry_gate_validation.csv"
    fieldnames = list(rows[0].keys()) if rows else []
    with open(out_path, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    print(f"\nDone — {len(rows)} rows written to {out_path}")

    # Print a summary breakdown
    approved = sum(1 for r in rows if r["filter_result"] == "APPROVED")
    pending  = sum(1 for r in rows if r["filter_result"] == "PENDING_FTA")
    skipped  = sum(1 for r in rows if r["filter_result"].startswith("SKIPPED"))
    print(f"\n  APPROVED:    {approved}")
    print(f"  PENDING_FTA: {pending}")
    print(f"  SKIPPED:     {skipped}")

    # Conviction distribution
    from collections import Counter
    conv_dist = Counter(r["conviction"] for r in rows if r["filter_result"] == "APPROVED")
    print(f"\n  Conviction distribution (APPROVED only):")
    for score in sorted(conv_dist):
        print(f"    score={score}: {conv_dist[score]}")
