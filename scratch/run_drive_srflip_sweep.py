"""
scratch/run_drive_srflip_sweep.py — OPEN_DRIVE + SR_FLIP detection-criteria sweep

OPEN_DRIVE parameters:
  DRIVE_ATR_MULT           — body must be >= this × ATR (current: 1.0)
  DRIVE_BODY_RANGE_RATIO_MIN — body/range >= this (current: 0.6)

SR_FLIP parameters:
  SR_FLIP_PULLBACK_ATR_TOL — pullback must reach within this × ATR of flip level (current: 0.5)

Strategy: same as Change 19 — tighten detection criteria to reduce low-quality instances
without gating/disabling admitted trades (avoids heat-occupier EngDD spike).

Usage:
    python3 scratch/run_drive_srflip_sweep.py

Baseline (Change 19 config):
  DRIVE_ATR_MULT=1.0, DRIVE_BODY_RANGE_RATIO_MIN=0.6, SR_FLIP_PULLBACK_ATR_TOL=0.5
"""
import copy
import importlib
import sys
import os
from datetime import datetime, timezone, timedelta
import time
import ccxt

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.structs import AssetConfig, OHLCV_Bar

# ── Sweep grid ────────────────────────────────────────────────────────────────
# Each entry: (label, drive_atr, drive_body_ratio, sr_pullback_tol)
# We sweep OPEN_DRIVE and SR_FLIP independently first, then combine winners.
SWEEP = [
    # label                        dr_atr  dr_body  sr_tol
    # ── Baseline ──────────────────────────────────────────
    ("baseline",                   1.0,    0.60,    0.50),
    # ── OPEN_DRIVE: tighten ATR mult only ─────────────────
    ("dr_atr1.25",                 1.25,   0.60,    0.50),
    ("dr_atr1.5",                  1.50,   0.60,    0.50),
    ("dr_atr1.75",                 1.75,   0.60,    0.50),
    # ── OPEN_DRIVE: tighten body ratio only ───────────────
    ("dr_body0.70",                1.0,    0.70,    0.50),
    ("dr_body0.75",                1.0,    0.75,    0.50),
    # ── OPEN_DRIVE: combine ───────────────────────────────
    ("dr_atr1.25_body0.70",        1.25,   0.70,    0.50),
    ("dr_atr1.5_body0.70",         1.50,   0.70,    0.50),
    ("dr_atr1.5_body0.75",         1.50,   0.75,    0.50),
    # ── SR_FLIP: tighten pullback tolerance ───────────────
    ("sr_tol0.25",                 1.0,    0.60,    0.25),
    ("sr_tol0.10",                 1.0,    0.60,    0.10),
    # ── Best DRIVE + best SR combined ─────────────────────
    ("dr_atr1.5_sr_tol0.25",       1.50,   0.60,    0.25),
    ("dr_atr1.5_body0.70_sr0.25",  1.50,   0.70,    0.25),
]

WARMUP_DAYS   = 30
BACKTEST_DAYS = 90
END_DT = datetime(2026, 6, 13, tzinfo=timezone.utc)


# ── Data fetch ────────────────────────────────────────────────────────────────
def fetch_bars(symbol, timeframe, start_ms, end_ms, limit=1000):
    ex = ccxt.binance({"enableRateLimit": True})
    bars, since = [], start_ms
    while since < end_ms:
        try:
            raw = ex.fetch_ohlcv(symbol, timeframe, since=since, limit=limit)
            if not raw:
                break
            tf_map = {"1h": "H1", "1d": "D1"}
            asset = symbol.split("/")[0]
            for row in raw:
                ts = row[0]
                if ts >= end_ms:
                    continue
                dt = datetime.fromtimestamp(ts / 1000, tz=timezone.utc)
                bars.append(OHLCV_Bar(
                    timestamp=dt, open=float(row[1]), high=float(row[2]),
                    low=float(row[3]), close=float(row[4]), volume=float(row[5]),
                    timeframe=tf_map.get(timeframe, timeframe), asset=asset,
                ))
            since = raw[-1][0] + 1
            time.sleep(ex.rateLimit / 1000)
        except Exception as e:
            print(f"  fetch error: {e}")
            break
    return bars


def build_bar_list(h1, d1):
    bars = h1 + d1
    bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == "D1" else 0))
    return bars


# ── State reset ───────────────────────────────────────────────────────────────
def reset_portfolio_state():
    for mod in [
        "bot.portfolio.heat",
        "bot.portfolio.drawdown",
        "bot.portfolio.ath_realization",
        "bot.portfolio.capitulation",
    ]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])


# ── Parameter patching ────────────────────────────────────────────────────────
def set_params(drive_atr, drive_body, sr_tol):
    import bot.config as cfg
    import bot.setup_detection.open_drive as od_mod
    import bot.setup_detection.sr_flip as sr_mod

    cfg.CONFIG["DRIVE_ATR_MULT"]              = drive_atr
    cfg.CONFIG["DRIVE_BODY_RANGE_RATIO_MIN"]  = drive_body
    cfg.CONFIG["SR_FLIP_PULLBACK_ATR_TOL"]    = sr_tol

    cfg.DRIVE_ATR_MULT             = drive_atr
    cfg.DRIVE_BODY_RANGE_RATIO_MIN = drive_body
    cfg.SR_FLIP_PULLBACK_ATR_TOL   = sr_tol

    od_mod.DRIVE_ATR_MULT             = drive_atr
    od_mod.DRIVE_BODY_RANGE_RATIO_MIN = drive_body
    sr_mod.SR_FLIP_PULLBACK_ATR_TOL   = sr_tol


# ── Cluster DD ────────────────────────────────────────────────────────────────
def cluster_dd(engine):
    trades = engine.trade_journal
    if not trades:
        return 0.0, 0.0
    WINDOW = timedelta(hours=3)
    for t in trades:
        peers = sum(
            1 for o in trades
            if o is not t
            and o.direction == t.direction
            and abs((o.entry_timestamp or t.entry_timestamp) -
                    (t.entry_timestamp or t.entry_timestamp)) <= WINDOW
        )
        t._clustered = peers > 0
    EQUITY = 100_000.0

    def _max_dd(subset):
        if not subset:
            return 0.0
        ordered = sorted(subset, key=lambda t: t.exit_timestamp or t.entry_timestamp)
        eq, peak, dd = EQUITY, EQUITY, 0.0
        for t in ordered:
            eq += t.realized_r * t.initial_risk_usd
            peak = max(peak, eq)
            dd = max(dd, (peak - eq) / peak)
        return dd

    clu = [t for t in trades if getattr(t, "_clustered", False)]
    iso = [t for t in trades if not getattr(t, "_clustered", False)]
    return _max_dd(clu) * 100, _max_dd(iso) * 100


# ── Per-type stats ─────────────────────────────────────────────────────────────
def type_stats(engine, name):
    by_type = engine.get_summary_stats().get("by_type_wr", {})
    d = by_type.get(name, {})
    n = d.get("wins", 0) + d.get("losses", 0)
    return n, (d["wins"] / n if n else 0.0), (d["total_r"] / n if n else 0.0)


# ── Main ──────────────────────────────────────────────────────────────────────
def main():
    warmup_start = END_DT - timedelta(days=WARMUP_DAYS + BACKTEST_DAYS)
    real_start   = END_DT - timedelta(days=BACKTEST_DAYS)
    end_ms       = int(END_DT.timestamp() * 1000)
    warmup_ms    = int(warmup_start.timestamp() * 1000)

    print("Fetching data...")
    all_h1 = fetch_bars("BTC/USDT", "1h", warmup_ms, end_ms)
    all_d1 = fetch_bars("BTC/USDT", "1d", warmup_ms, end_ms)

    warmup_bars = build_bar_list(
        [b for b in all_h1 if b.timestamp < real_start],
        [b for b in all_d1 if b.timestamp < real_start],
    )
    real_bars = build_bar_list(
        [b for b in all_h1 if b.timestamp >= real_start],
        [b for b in all_d1 if b.timestamp >= real_start],
    )
    print(f"Warmup bars: {len(warmup_bars)}, Real bars: {len(real_bars)}\n")

    # ── Header ────────────────────────────────────────────────────────────────
    print(
        f"{'Label':<32} {'Tot':>4} {'WR':>6} {'AvgR':>6} {'EngDD':>7} "
        f"{'HeatSk':>7} "
        f"{'OD_n':>5} {'OD_WR':>6} {'OD_R':>6} "
        f"{'SR_n':>5} {'SR_WR':>6} {'SR_R':>6} "
        f"{'CluDD':>7} {'IsoDD':>7}"
    )
    print("─" * 125)

    # ── Warmup ONCE with baseline params ──────────────────────────────────────
    print("Running warmup (once)...")
    set_params(*SWEEP[0][1:])

    from bot.backtesting.engine import BacktestEngine
    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    warmup_engine = BacktestEngine(initial_equity=100_000.0)
    warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    for b in warmup_bars:
        warmup_engine.step(b, oi=0.0, liq=0.0)

    from bot.market_context import pivot_registry as pr_mod
    from bot.indicators.registry import Indicators, _buffers
    from bot.data_ingestion.ohlcv_buffer import buffer as ohlcv_buffer

    saved_pr   = copy.deepcopy(pr_mod.pivot_registry)
    saved_ind  = copy.deepcopy(Indicators)
    saved_ibu  = copy.deepcopy(_buffers)
    saved_ohlcv = copy.deepcopy(ohlcv_buffer)
    saved_pf   = list(warmup_engine._pending_fills)
    saved_ask  = set(warmup_engine._active_setup_keys)
    print("Warmup complete.\n")

    # ── Sweep ─────────────────────────────────────────────────────────────────
    results = []
    for label, drive_atr, drive_body, sr_tol in SWEEP:
        print(f"  Starting: {label}", flush=True)

        pr_mod.pivot_registry.clear()
        pr_mod.pivot_registry.update(copy.deepcopy(saved_pr))
        Indicators.clear(); Indicators.update(copy.deepcopy(saved_ind))
        _buffers.clear();   _buffers.update(copy.deepcopy(saved_ibu))
        ohlcv_buffer.clear(); ohlcv_buffer.update(copy.deepcopy(saved_ohlcv))
        reset_portfolio_state()
        set_params(drive_atr, drive_body, sr_tol)

        engine = BacktestEngine(initial_equity=100_000.0)
        engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        engine._pending_fills     = list(saved_pf)
        engine._active_setup_keys = set(saved_ask)

        for b in real_bars:
            engine.step(b, oi=0.0, liq=0.0)

        stats   = engine.get_summary_stats()
        skips   = stats.get("skipped_reasons", {})
        heat_sk = skips.get("HEAT_CAP", 0) + skips.get("CORRELATED_HEAT_CAP", 0)
        clu_dd, iso_dd = cluster_dd(engine)

        od_n, od_wr, od_r = type_stats(engine, "OPEN_DRIVE")
        sr_n, sr_wr, sr_r = type_stats(engine, "SR_FLIP")

        row = dict(
            label=label,
            total=stats.get("total_trades", 0),
            wr=stats.get("win_rate", 0) * 100,
            avg_r=stats.get("avg_r", 0),
            engine_dd=stats.get("max_drawdown_pct", 0),
            heat_sk=heat_sk,
            od_n=od_n, od_wr=od_wr * 100, od_r=od_r,
            sr_n=sr_n, sr_wr=sr_wr * 100, sr_r=sr_r,
            clu_dd=clu_dd, iso_dd=iso_dd,
        )
        results.append(row)

        print(
            f"{label:<32} {row['total']:>4} {row['wr']:>5.1f}% {row['avg_r']:>+6.2f} "
            f"{row['engine_dd']:>6.2f}% "
            f"{heat_sk:>7} "
            f"{od_n:>5} {od_wr*100:>5.1f}% {od_r:>+6.2f} "
            f"{sr_n:>5} {sr_wr*100:>5.1f}% {sr_r:>+6.2f} "
            f"{clu_dd:>6.2f}% {iso_dd:>6.2f}%"
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    valid = [r for r in results if r["total"] > 0]
    if not valid:
        print("\nNo valid results.")
        return

    print("\n--- Best by Engine DD ---")
    best = min(valid, key=lambda r: r["engine_dd"])
    print(f"  {best['label']}: EngDD={best['engine_dd']:.2f}%, WR={best['wr']:.1f}%, AvgR={best['avg_r']:+.2f}")

    print("--- Best by Avg R ---")
    best = max(valid, key=lambda r: r["avg_r"])
    print(f"  {best['label']}: AvgR={best['avg_r']:+.2f}, EngDD={best['engine_dd']:.2f}%, WR={best['wr']:.1f}%")

    print("--- Best by WR ---")
    best = max(valid, key=lambda r: r["wr"])
    print(f"  {best['label']}: WR={best['wr']:.1f}%, EngDD={best['engine_dd']:.2f}%, AvgR={best['avg_r']:+.2f}")


if __name__ == "__main__":
    main()
