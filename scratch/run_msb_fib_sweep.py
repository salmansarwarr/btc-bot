"""
scratch/run_msb_fib_sweep.py — Fib band / ATR cap sweep for MSB_SHALLOW and MSB_DEEP

Sweeps tighter detection criteria across SHALLOW_FIB_MIN/MAX, DEEP_FIB_MIN/MAX,
and SHALLOW_ATR_CAP_MULT. Each combination gets a full warmup pass + real pass.

Usage:
    python3 scratch/run_msb_fib_sweep.py

Baseline (current config):
    SHALLOW_FIB: 0.236–0.382, SHALLOW_ATR_CAP: 3.0
    DEEP_FIB:    0.55–0.85

Goal: reduce MSB detection count without gating/disabling admitted trades.
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
# Each entry: (label, shallow_min, shallow_max, shallow_atr_cap, deep_min, deep_max)
SWEEP = [
    # label                       sh_min  sh_max  sh_atr  dp_min  dp_max
    ("baseline",                  0.236,  0.382,  3.0,    0.55,   0.85),
    # Tighten shallow band only
    ("sh_0.30-0.382",             0.30,   0.382,  3.0,    0.55,   0.85),
    ("sh_0.30-0.382_cap2.0",      0.30,   0.382,  2.0,    0.55,   0.85),
    # Tighten deep to golden zone only (0.618–0.786)
    ("dp_golden",                 0.236,  0.382,  3.0,    0.618,  0.786),
    # Tighten both
    ("sh+dp_tight",               0.30,   0.382,  3.0,    0.618,  0.786),
    ("sh+dp_tight_cap2.0",        0.30,   0.382,  2.0,    0.618,  0.786),
    # Looser shallow cap but tighter Fib bands
    ("sh_tight_dp_golden_cap1.5", 0.30,   0.382,  1.5,    0.618,  0.786),
    # Very tight shallow (0.35–0.382 = right at golden ratio)
    ("sh_0.35-0.382",             0.35,   0.382,  3.0,    0.55,   0.85),
    ("sh_0.35-0.382_dp_golden",   0.35,   0.382,  3.0,    0.618,  0.786),
]

WARMUP_DAYS   = 30
BACKTEST_DAYS = 90
END_DT = datetime(2026, 6, 13, tzinfo=timezone.utc)


# ── Data fetch (once) ─────────────────────────────────────────────────────────
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


def build_bar_list(h1_bars, d1_bars):
    all_bars = h1_bars + d1_bars
    all_bars.sort(key=lambda b: (b.timestamp.timestamp(), 1 if b.timeframe == "D1" else 0))
    return all_bars


# ── Global state reset (portfolio only) ──────────────────────────────────────
def reset_portfolio_state():
    """Reset only portfolio/heat modules. Pivot registry and indicators are
    restored via snapshot; do NOT reload them here."""
    mods_to_reload = [
        "bot.portfolio.heat",
        "bot.portfolio.drawdown",
        "bot.portfolio.ath_realization",
        "bot.portfolio.capitulation",
    ]
    for mod in mods_to_reload:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])


# ── Parameter patching ────────────────────────────────────────────────────────
def set_msb_params(sh_min, sh_max, sh_atr, dp_min, dp_max):
    """
    Patch both CONFIG dict and module-level aliases in bot.config and
    bot.setup_detection.msb_pullback (which imports at module level).
    Per Change 12 sweep infrastructure: module-level constants must be
    patched via direct attribute assignment.
    """
    import bot.config as cfg
    import bot.setup_detection.msb_pullback as msb_mod

    cfg.CONFIG["SHALLOW_FIB_MIN"]      = sh_min
    cfg.CONFIG["SHALLOW_FIB_MAX"]      = sh_max
    cfg.CONFIG["SHALLOW_ATR_CAP_MULT"] = sh_atr
    cfg.CONFIG["DEEP_FIB_MIN"]         = dp_min
    cfg.CONFIG["DEEP_FIB_MAX"]         = dp_max

    cfg.SHALLOW_FIB_MIN      = sh_min
    cfg.SHALLOW_FIB_MAX      = sh_max
    cfg.SHALLOW_ATR_CAP_MULT = sh_atr
    cfg.DEEP_FIB_MIN         = dp_min
    cfg.DEEP_FIB_MAX         = dp_max

    msb_mod.SHALLOW_FIB_MIN      = sh_min
    msb_mod.SHALLOW_FIB_MAX      = sh_max
    msb_mod.SHALLOW_ATR_CAP_MULT = sh_atr
    msb_mod.DEEP_FIB_MIN         = dp_min
    msb_mod.DEEP_FIB_MAX         = dp_max


# ── Cluster analysis ──────────────────────────────────────────────────────────
def cluster_dd(engine):
    """Return (clustered_dd, isolated_dd) from the engine's trade journal."""
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

    clustered = [t for t in trades if getattr(t, "_clustered", False)]
    isolated  = [t for t in trades if not getattr(t, "_clustered", False)]
    return _max_dd(clustered) * 100, _max_dd(isolated) * 100


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

    # ── Print header ──────────────────────────────────────────────────────────
    print(
        f"{'Label':<30} {'Tot':>4} {'WR':>6} {'AvgR':>6} {'EngDD':>7} "
        f"{'HeatSk':>7} "
        f"{'SH_n':>5} {'SH_WR':>6} {'SH_R':>6} "
        f"{'DP_n':>5} {'DP_WR':>6} {'DP_R':>6} "
        f"{'CluDD':>7} {'IsoDD':>7}"
    )
    print("-" * 120)

    # ── Run warmup ONCE with baseline params ──────────────────────────────────
    print("Running warmup pass (once)...")
    set_msb_params(*SWEEP[0][1:])  # baseline params

    from bot.backtesting.engine import BacktestEngine
    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    warmup_engine = BacktestEngine(initial_equity=100_000.0)
    warmup_engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
    for b in warmup_bars:
        warmup_engine.step(b, oi=0.0, liq=0.0)

    # ── Snapshot all module-level state post-warmup ───────────────────────────
    from bot.market_context import pivot_registry as pr_mod
    from bot.indicators.registry import Indicators, _buffers
    from bot.data_ingestion.ohlcv_buffer import buffer as ohlcv_buffer

    saved_pivot_registry    = copy.deepcopy(pr_mod.pivot_registry)
    saved_indicators        = copy.deepcopy(Indicators)
    saved_ind_buffers       = copy.deepcopy(_buffers)
    saved_ohlcv_buffer      = copy.deepcopy(ohlcv_buffer)
    saved_pending_fills     = list(warmup_engine._pending_fills)
    saved_active_setup_keys = set(warmup_engine._active_setup_keys)

    print("Warmup complete.")
    print(f"  H1 pivots: {len(pr_mod.pivot_registry.get('BTC', {}).get('H1', []))}, "
          f"D1 pivots: {len(pr_mod.pivot_registry.get('BTC', {}).get('D1', []))}")
    h1_state = Indicators.get("BTC", {}).get("H1")
    print(f"  H1 ATR: {h1_state.atr_14 if h1_state else 'NO STATE'}\n")

    # ── Sweep loop ────────────────────────────────────────────────────────────
    results = []
    for label, sh_min, sh_max, sh_atr, dp_min, dp_max in SWEEP:
        print(f"  Starting: {label}", flush=True)

        # Restore all module-level state to post-warmup snapshot
        pr_mod.pivot_registry.clear()
        pr_mod.pivot_registry.update(copy.deepcopy(saved_pivot_registry))

        Indicators.clear()
        Indicators.update(copy.deepcopy(saved_indicators))

        _buffers.clear()
        _buffers.update(copy.deepcopy(saved_ind_buffers))

        ohlcv_buffer.clear()
        ohlcv_buffer.update(copy.deepcopy(saved_ohlcv_buffer))

        # Reset portfolio state only (preserves pivot/indicator modules)
        reset_portfolio_state()

        # Patch Fib parameters for this sweep iteration
        set_msb_params(sh_min, sh_max, sh_atr, dp_min, dp_max)

        # Fresh engine with restored warmup fill queue
        engine = BacktestEngine(initial_equity=100_000.0)
        engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        engine._pending_fills      = list(saved_pending_fills)
        engine._active_setup_keys  = set(saved_active_setup_keys)

        for b in real_bars:
            engine.step(b, oi=0.0, liq=0.0)

        stats   = engine.get_summary_stats()
        by_type = stats.get("by_type_wr", {})

        def s(name):
            d = by_type.get(name, {})
            n = d.get("wins", 0) + d.get("losses", 0)
            return n, (d["wins"] / n if n else 0.0), (d["total_r"] / n if n else 0.0)

        sh_n, sh_wr, sh_avg = s("MSB_SHALLOW")
        dp_n, dp_wr, dp_avg = s("MSB_DEEP")
        skips   = stats.get("skipped_reasons", {})
        heat_sk = skips.get("HEAT_CAP", 0) + skips.get("CORRELATED_HEAT_CAP", 0)
        clu_dd, iso_dd = cluster_dd(engine)

        row = dict(
            label=label, total=stats["total_trades"],
            wr=stats.get("win_rate", 0) * 100, avg_r=stats.get("avg_r", 0),
            engine_dd=stats.get("max_drawdown_pct", 0),
            heat_sk=heat_sk,
            sh_n=sh_n, sh_wr=sh_wr * 100, sh_avg=sh_avg,
            dp_n=dp_n, dp_wr=dp_wr * 100, dp_avg=dp_avg,
            clu_dd=clu_dd, iso_dd=iso_dd,
        )
        results.append(row)

        print(
            f"{label:<30} {row['total']:>4} {row['wr']:>5.1f}% {row['avg_r']:>+6.2f} "
            f"{row['engine_dd']:>6.2f}% "
            f"{heat_sk:>7} "
            f"{sh_n:>5} {sh_wr*100:>5.1f}% {sh_avg:>+6.2f} "
            f"{dp_n:>5} {dp_wr*100:>5.1f}% {dp_avg:>+6.2f} "
            f"{clu_dd:>6.2f}% {iso_dd:>6.2f}%"
        )

    # ── Summary ───────────────────────────────────────────────────────────────
    print("\n--- Best by Engine DD ---")
    best_dd = min(results, key=lambda r: r["engine_dd"])
    print(f"  {best_dd['label']}: EngDD={best_dd['engine_dd']:.2f}%, "
          f"WR={best_dd['wr']:.1f}%, AvgR={best_dd['avg_r']:+.2f}")

    print("--- Best by Avg R ---")
    best_r = max(results, key=lambda r: r["avg_r"])
    print(f"  {best_r['label']}: AvgR={best_r['avg_r']:+.2f}, "
          f"EngDD={best_r['engine_dd']:.2f}%, WR={best_r['wr']:.1f}%")

    print("--- Best by WR ---")
    best_wr = max(results, key=lambda r: r["wr"])
    print(f"  {best_wr['label']}: WR={best_wr['wr']:.1f}%, "
          f"EngDD={best_wr['engine_dd']:.2f}%, AvgR={best_wr['avg_r']:+.2f}")


if __name__ == "__main__":
    main()