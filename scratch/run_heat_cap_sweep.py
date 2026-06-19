"""
scratch/run_heat_cap_sweep.py — Portfolio Heat Capacity sweep

Sweeps MAX_HEAT_PCT across the TEST / OOS segment to analyze the
impact of clustered trade toxicity and optimal concurrency limits.

Usage:
    python3 scratch/run_heat_cap_sweep.py
"""
import copy
import importlib
import sys
import os
from datetime import timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bot.structs import AssetConfig
from walk_forward import WINDOWS, fetch_bars, build_sorted, INITIAL_EQUITY

SWEEP = [
    # label        max_heat  max_corr
    ("heat_0.08",  0.08,     0.08),
    ("heat_0.06",  0.06,     0.06), # Baseline
    ("heat_0.05",  0.05,     0.05),
    ("heat_0.04",  0.04,     0.04),
    ("heat_0.03",  0.03,     0.03),
    ("heat_0.02",  0.02,     0.02),
]

END_DT = WINDOWS["test"].end
WARMUP_DAYS = 30
BACKTEST_DAYS = 90

def reset_portfolio_state():
    for mod in [
        "bot.portfolio.heat",
        "bot.portfolio.drawdown",
        "bot.portfolio.ath_realization",
        "bot.portfolio.capitulation",
    ]:
        if mod in sys.modules:
            importlib.reload(sys.modules[mod])

def set_heat_params(max_heat, max_corr):
    import bot.config as cfg
    import bot.portfolio.heat as heat_mod

    cfg.CONFIG["MAX_HEAT_PCT"]             = max_heat
    cfg.CONFIG["MAX_CORRELATED_HEAT_PCT"]  = max_corr

    cfg.MAX_HEAT_PCT             = max_heat
    cfg.MAX_CORRELATED_HEAT_PCT  = max_corr

    heat_mod.MAX_HEAT_PCT             = max_heat
    heat_mod.MAX_CORRELATED_HEAT_PCT  = max_corr

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

    clustered = [t for t in trades if getattr(t, "_clustered", False)]
    isolated  = [t for t in trades if not getattr(t, "_clustered", False)]
    return _max_dd(clustered) * 100, _max_dd(isolated) * 100

def main():
    warmup_start = END_DT - timedelta(days=WARMUP_DAYS + BACKTEST_DAYS)
    real_start   = END_DT - timedelta(days=BACKTEST_DAYS)
    end_ms       = int(END_DT.timestamp() * 1000)
    warmup_ms    = int(warmup_start.timestamp() * 1000)

    print("Fetching TEST/OOS data...")
    all_h1 = fetch_bars("BTC/USDT", "1h", warmup_ms, end_ms)
    all_d1 = fetch_bars("BTC/USDT", "1d", warmup_ms, end_ms)

    warmup_bars = build_sorted(
        [b for b in all_h1 if b.timestamp < real_start],
        [b for b in all_d1 if b.timestamp < real_start],
    )
    real_bars = build_sorted(
        [b for b in all_h1 if b.timestamp >= real_start],
        [b for b in all_d1 if b.timestamp >= real_start],
    )
    print(f"Warmup bars: {len(warmup_bars)}, Real bars: {len(real_bars)}\n")

    print(
        f"{'Label':<15} {'Tot':>4} {'WR':>6} {'AvgR':>6} {'EngDD':>7} "
        f"{'HeatSk':>6} {'CluDD':>7} {'IsoDD':>7}"
    )
    print("─" * 70)

    set_heat_params(*SWEEP[1][1:]) # baseline

    from bot.backtesting.engine import BacktestEngine
    from bot.data_ingestion.feed_manager import feeds, ExternalFeedState
    if "BTC" not in feeds:
        feeds["BTC"] = ExternalFeedState(asset="BTC")

    warmup_engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
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

    results = []
    for label, max_h, max_c in SWEEP:
        pr_mod.pivot_registry.clear()
        pr_mod.pivot_registry.update(copy.deepcopy(saved_pr))
        Indicators.clear(); Indicators.update(copy.deepcopy(saved_ind))
        _buffers.clear();   _buffers.update(copy.deepcopy(saved_ibu))
        ohlcv_buffer.clear(); ohlcv_buffer.update(copy.deepcopy(saved_ohlcv))
        reset_portfolio_state()
        
        set_heat_params(max_h, max_c)

        engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
        engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        engine._pending_fills     = list(saved_pf)
        engine._active_setup_keys = set(saved_ask)

        for b in real_bars:
            engine.step(b, oi=0.0, liq=0.0)

        stats   = engine.get_summary_stats()
        skips   = stats.get("skipped_reasons", {})
        heat_sk = skips.get("HEAT_CAP", 0) + skips.get("CORRELATED_HEAT_CAP", 0)
        clu_dd, iso_dd = cluster_dd(engine)

        row = dict(
            label=label,
            total=stats.get("total_trades", 0),
            wr=stats.get("win_rate", 0) * 100,
            avg_r=stats.get("avg_r", 0),
            engine_dd=stats.get("max_drawdown_pct", 0),
            heat_sk=heat_sk, clu_dd=clu_dd, iso_dd=iso_dd,
        )
        results.append(row)

        print(
            f"{label:<15} {row['total']:>4} {row['wr']:>5.1f}% {row['avg_r']:>+6.2f} "
            f"{row['engine_dd']:>6.2f}% "
            f"{heat_sk:>6} {clu_dd:>6.2f}% {iso_dd:>6.2f}%"
        )

    print("\n--- Best by Engine DD ---")
    best_dd = min(results, key=lambda r: r["engine_dd"])
    print(f"  {best_dd['label']}: EngDD={best_dd['engine_dd']:.2f}%, WR={best_dd['wr']:.1f}%, AvgR={best_dd['avg_r']:+.2f}")

    print("--- Best by Avg R ---")
    best_r = max(results, key=lambda r: r["avg_r"])
    print(f"  {best_r['label']}: AvgR={best_r['avg_r']:+.2f}, EngDD={best_r['engine_dd']:.2f}%, WR={best_r['wr']:.1f}%")

if __name__ == "__main__":
    main()
