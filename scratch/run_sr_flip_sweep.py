"""
scratch/run_sr_flip_sweep.py — SR_FLIP detection tightening sweep

Parameters:
  FLIP_CONFIRM_BARS   — bars to confirm bounce (baseline: 1)
  FLIP_ATR_MULT       — bounce candle must move >= this × ATR (baseline: 0.0)
  FLIP_BODY_RATIO_MIN — bounce candle body/total-range ratio (baseline: 0.0)

Strategy: identify weakest flip confirmation criteria and tighten them without
gating/disabling to avoid the concurrent exposure DD spike.
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
    # label                        bars  atr_m  body_m
    # ── Baseline ─────────────────────────────────────────
    ("baseline",                   1,    0.0,   0.0),
    # ── ATR tighten ──────────────────────────────────────
    ("atr_0.5",                    1,    0.5,   0.0),
    ("atr_1.0",                    1,    1.0,   0.0),
    ("atr_1.2",                    1,    1.2,   0.0),
    # ── Body ratio tighten ───────────────────────────────
    ("body_0.5",                   1,    0.0,   0.5),
    ("body_0.65",                  1,    0.0,   0.65),
    # ── Combined ─────────────────────────────────────────
    ("atr1.0_body0.5",             1,    1.0,   0.5),
    ("atr1.2_body0.65",            1,    1.2,   0.65),
    # ── Multiple confirm bars ────────────────────────────
    ("bars_2",                     2,    0.0,   0.0),
    ("bars_2_atr0.5",              2,    0.5,   0.0),
]

END_DT = WINDOWS["train"].end
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


def set_params(confirm_bars, atr_mult, body_ratio):
    import bot.config as cfg
    import bot.setup_detection.sr_flip as sr_mod

    cfg.CONFIG["FLIP_CONFIRM_BARS"]   = confirm_bars
    cfg.CONFIG["FLIP_ATR_MULT"]       = atr_mult
    cfg.CONFIG["FLIP_BODY_RATIO_MIN"] = body_ratio

    cfg.FLIP_CONFIRM_BARS             = confirm_bars
    cfg.FLIP_ATR_MULT                 = atr_mult
    cfg.FLIP_BODY_RATIO_MIN           = body_ratio

    sr_mod.FLIP_CONFIRM_BARS          = confirm_bars
    sr_mod.FLIP_ATR_MULT              = atr_mult
    sr_mod.FLIP_BODY_RATIO_MIN        = body_ratio


def type_stats(engine, name):
    by_type = engine.get_summary_stats().get("by_type_wr", {})
    d = by_type.get(name, {})
    n = d.get("wins", 0) + d.get("losses", 0)
    return n, (d["wins"] / n if n else 0.0), (d["total_r"] / n if n else 0.0)


def main():
    warmup_start = END_DT - timedelta(days=WARMUP_DAYS + BACKTEST_DAYS)
    real_start   = END_DT - timedelta(days=BACKTEST_DAYS)
    end_ms       = int(END_DT.timestamp() * 1000)
    warmup_ms    = int(warmup_start.timestamp() * 1000)

    print("Fetching data...")
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
        f"{'Label':<20} {'Tot':>4} {'WR':>6} {'AvgR':>6} {'EngDD':>7} "
        f"{'HeatSk':>6} "
        f"{'SR_n':>5} {'SR_WR':>6} {'SR_R':>6}"
    )
    print("─" * 80)

    # ── Warmup ONCE with baseline params ──────────────────────────────────────
    set_params(*SWEEP[0][1:])

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

    # ── Sweep ─────────────────────────────────────────────────────────────────
    results = []
    for label, bars_p, atr_p, body_p in SWEEP:
        pr_mod.pivot_registry.clear()
        pr_mod.pivot_registry.update(copy.deepcopy(saved_pr))
        Indicators.clear(); Indicators.update(copy.deepcopy(saved_ind))
        _buffers.clear();   _buffers.update(copy.deepcopy(saved_ibu))
        ohlcv_buffer.clear(); ohlcv_buffer.update(copy.deepcopy(saved_ohlcv))
        reset_portfolio_state()
        
        set_params(bars_p, atr_p, body_p)

        engine = BacktestEngine(initial_equity=INITIAL_EQUITY)
        engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        engine._pending_fills     = list(saved_pf)
        engine._active_setup_keys = set(saved_ask)

        for b in real_bars:
            engine.step(b, oi=0.0, liq=0.0)

        stats   = engine.get_summary_stats()
        skips   = stats.get("skipped_reasons", {})
        heat_sk = skips.get("HEAT_CAP", 0) + skips.get("CORRELATED_HEAT_CAP", 0)

        sr_n, sr_wr, sr_r = type_stats(engine, "SR_FLIP")

        row = dict(
            label=label,
            total=stats.get("total_trades", 0),
            wr=stats.get("win_rate", 0) * 100,
            avg_r=stats.get("avg_r", 0),
            engine_dd=stats.get("max_drawdown_pct", 0),
            heat_sk=heat_sk,
            sr_n=sr_n, sr_wr=sr_wr * 100, sr_r=sr_r,
        )
        results.append(row)

        print(
            f"{label:<20} {row['total']:>4} {row['wr']:>5.1f}% {row['avg_r']:>+6.2f} "
            f"{row['engine_dd']:>6.2f}% "
            f"{heat_sk:>6} "
            f"{sr_n:>5} {sr_wr*100:>5.1f}% {sr_r:>+6.2f}"
        )

    valid = [r for r in results if r["total"] > 0]
    if valid:
        print("\n--- Best by Engine DD ---")
        best = min(valid, key=lambda r: r["engine_dd"])
        print(f"  {best['label']}: EngDD={best['engine_dd']:.2f}%, WR={best['wr']:.1f}%, AvgR={best['avg_r']:+.2f}")

        print("--- Best by Avg R ---")
        best = max(valid, key=lambda r: r["avg_r"])
        print(f"  {best['label']}: AvgR={best['avg_r']:+.2f}, EngDD={best['engine_dd']:.2f}%, WR={best['wr']:.1f}%")


if __name__ == "__main__":
    main()
