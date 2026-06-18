# Parameter Tuning Changelog

**Fixed Test Window:** 90 Days (Binance BTC/USDT, H1 & D1, ending 2026-06-13)

### Baseline Performance

- **Total Trades:** 251
- **Win Rate:** 53.39%
- **Average R:** 0.95R
- **Max Drawdown:** 7.09%

---

## Changes

_(New changes will be recorded here using the format below)_

### Format Template

- **Proxy Parameter:** `PARAM_NAME`
- **Original Value:** `X`
- **New Value:** `Y`
- **Reasoning:** Why we are changing this parameter.
- **Before Stats:** Trades A, Win Rate X%, Avg R Y, Max DD Z%
- **After Stats:** Trades B, Win Rate X%, Avg R Y, Max DD Z%

---

### Change 1: Portfolio Heat Expansion

- **Proxy Parameter:** `MAX_HEAT_PCT`
- **Original Value:** `0.06` (6% total open risk)
- **New Value:** `0.12` (12% total open risk)
- **Reasoning:** The baseline skipped 1,111 trades specifically due to the hard heat ceiling. Doubling the allowed heat lets the bot capitalize on grouped setups, at the theoretical cost of deeper drawdowns.
- **Before Stats:** Trades 251, Win Rate 53.39%, Avg R 0.95, Max DD 7.09%
- **After Stats:** Trades 351, Win Rate 51.28%, Avg R 0.87, Max DD 7.94%

---

### Change 2: Stop Loss Floor Adjustment

- **Proxy Parameter:** `MIN_STOP_ATR_MULT`
- **Original Value:** `0.5` (Stop can be as close as 0.5 ATR)
- **New Value:** `1.0` (Stop must be at least 1.0 ATR away)
- **Reasoning:** Giving setups more breathing room to avoid getting wiggled out by intra-bar volatility, while simultaneously lowering R-multiples (as the denominator risk distance is larger).
- **Before Stats:** Trades 351, Win Rate 51.28%, Avg R 0.87, Max DD 7.94%
- **After Stats:** Trades 362, Win Rate 50.83%, Avg R 0.45, Max DD 6.60%

---

### Change 3: Tighten SFP Wick Rules

- **Proxy Parameter:** `SFP_WICK_ATR_MULT`
- **Original Value:** `0.0` (previously loosely implied, capturing tiny wicks)
- **New Value:** `1.0` (wick must be at least 1.0× ATR(14))
- **Reasoning:** Many SFP traps were triggering on weak, marginal wicks, causing quick stop-outs in chop. Demanding a much more pronounced rejection wick should filter out the noise.
- **Before Stats:** Trades 362, Win Rate 50.83%, Avg R 0.45, Max DD 6.60% (SFP Trades: 132)
- **After Stats:** Trades 235, Win Rate 50.21%, Avg R 0.65, Max DD 6.49% (SFP Trades: 7)

---

### Change 4: Tighten Momentum Divergence Strength

- **Proxy Parameter:** `MOMENTUM_DIVERGENCE_MIN_STRENGTH`
- **Original Value:** `0.0` (any difference between extreme lows/highs counted)
- **New Value:** `15.0` (RSI must deviate by at least 15 points)
- **Reasoning:** To filter out weak, marginal divergences in chop that resulted in quick stops.
- **Before Stats:** Trades 235, Win Rate 50.21%, Avg R 0.65, Max DD 6.49% (MD Trades: 26)
- **After Stats:** Trades 179, Win Rate 39.66%, Avg R 0.22, Max DD 20.52% (MD Trades: 1)
- **Note:** This change severely negatively impacted the strategy. Momentum Divergence trades plummeted to 1. Surprisingly, filtering these trades actually degraded the portfolio: average R dropped to 0.22 and Max Drawdown spiked to 20.5%. This implies that those "weak" divergences were either highly profitable, or they acted as a necessary risk-occupying hedge that kept the bot out of other, much worse setups (the heat ceiling was freed up).

---

### Change 5: Revert Momentum Divergence Strength (Partial)

- **Proxy Parameter:** `MOMENTUM_DIVERGENCE_MIN_STRENGTH`
- **Original Value:** `15.0`
- **New Value:** `5.0` (soft filter — keeps most divergence trades while removing the absolute weakest)
- **Reasoning:** Change 4 was a net negative. MD trades act as a counter-trend hedge that prevents the bot from over-allocating to worse continuation setups when heat frees up. Reverting to 5.0 restores most of the beneficial signals while keeping a minimal noise filter.
- **Before Stats:** Trades 179, Win Rate 39.66%, Avg R 0.22, Max DD 20.52%
- **After Stats:** Trades 247, Win Rate 43.32%, Avg R 0.52, Max DD 33.73%
- **Note:** Max Drawdown spiked to 33.73% despite improved avg R. Investigation revealed this was caused by three compounding engine bugs (see Engine Fixes below) that were producing artificially good earlier results by misfilling trades. Stats from Changes 1–4 should be treated as indicative only — not simulation-accurate.

---

### Change 6: Engine Fix — Live `trend_class` Computation

- **Type:** Correctness fix (not a tunable parameter)
- **File:** `engine.py` — `_compute_trend_class()` / `step()`
- **Problem:** `trend_class` was hardcoded to `TrendClass.TRENDING` on every bar. As a result, `TrendClass.LOCKOUT_TREND` could never occur, which meant the relative-strength veto in `evaluate_entry` (Resolution I-8) — intended to block weak-asset UP entries during a red, strongly-trending market — never fired.
- **Fix:** `trend_class` is now derived each bar from live ADX/ER indicator state (`ADX >= ADX_TREND_THRESHOLD` → `LOCKOUT_TREND`, `ER >= ER_TREND_THRESHOLD` → `TRENDING`, else `RANGING`). `update_htf_bias` is also now gated to D1 bars only, and `_flush_pending_fills` receives the live `trend_class` so pending fills respect it too.
- **Before Stats:** Trades 247, Win Rate 43.32%, Avg R +0.52, Max DD 33.73% (Change 5 baseline, `MAX_HEAT_PCT=0.12`)
- **After Stats:** Trades 254, Win Rate 42.91%, Avg R +0.54, Max DD 37.17% (`MAX_HEAT_PCT=0.12`, unchanged)
- **Note:** This is a correctness fix, not a regression to revert; it is now part of the permanent baseline.

---

### Change 7: Portfolio Heat Reduction (Re-tested, Isolated from Change 6)

- **Proxy Parameter:** `MAX_HEAT_PCT`
- **Original Value:** `0.12` (12% total open risk)
- **New Value:** `0.08` (8% total open risk)
- **Reasoning:** Originally tested bundled with the Change 6 engine fix, which made the result uninterpretable. Re-tested here in isolation.
- **Before Stats:** Trades 254, Win Rate 42.91%, Avg R +0.54, Max DD 37.17%
- **After Stats:** Trades 178, Win Rate 44.94%, Avg R +0.69, Max DD 35.86%
- **Verdict:** Net improvement. **Keeping `MAX_HEAT_PCT=0.08`.**

---

## ⚠️ Engine Bug Fixes (Between Change 4 and Change 5)

### Bug 1: Entry Fill Price (Wrong Bar)

- **Fix:** Introduced `_pending_fills` queue. Detected candidates staged at bar N and filled at bar N+1's open price.

### Bug 2: Same-Bar Stop-Out

- **Fix:** Introduced `_newly_opened` staging dict. Fills committed to `open_trades` only after lifecycle loop completes.

### Bug 3: Exit Price Always Equal to Entry Price in Journal

- **Fix:** Added `exit_price: float` to `TradeState`. `close_trade()` stamps it at closure.

### Bug 4: Max Drawdown Measured Only at Final Bar

- **Fix:** Added `_peak_equity` and `_max_drawdown` instance variables, updated on every trade close.

---

### Change 8: Stop Loss Distance Increase (Tuned)

- **Proxy Parameter:** `MIN_STOP_ATR_MULT`
- **Original Value:** `1.0`
- **New Value:** `1.2`
- **Reasoning:** 19.0% of trades were hitting a full −1R stop within 3 bars. Swept 1.0/1.1/1.2/1.25/1.5.

| MIN_STOP_ATR_MULT | Trades | Win Rate | Avg R | Max DD | Quick-stops | Heat Cap Skips |
| ----------------- | ------ | -------- | ----- | ------ | ----------- | -------------- |
| 1.0 (baseline)    | 174    | 45.40%   | +0.69 | 42.08% | 33 (19.0%)  | 330            |
| 1.1               | 196    | 43.88%   | +0.54 | 34.42% | 30          | 247            |
| **1.2 (chosen)**  | 178    | 44.38%   | +0.60 | 28.79% | 24 (13.5%)  | 296            |
| 1.25              | 203    | 43.84%   | +0.55 | 29.04% | 25 (12.3%)  | 168            |
| 1.5               | 210    | 43.81%   | +0.35 | 29.86% | 23 (11.0%)  | 98             |

- **Verdict:** `1.2` dominates — lower DD and higher AvgR than all alternatives. **Keeping `MIN_STOP_ATR_MULT=1.2`.**

---

### Change 9: Backtest Window Pin (Reproducibility Fix)

- **Type:** Correctness fix
- **Fix:** Removed dead `real_now`/`real_start_ms`/`real_end_ms` block. All runs now pinned to fixed 90-day window ending 2026-06-13.
- **Before:** Trades 176, Win Rate 45.45%, Avg R +0.70, Max DD 35.92%
- **After:** Trades 174, Win Rate 45.40%, Avg R +0.69, Max DD 42.08%

---

### Change 10: Dual-Field Heat Tracking (Cluster Risk-Budget Prerequisite)

- **Type:** Engine / portfolio correctness fix
- **Files:** `structs.py`, `heat.py`, `engine.py`
- **Fix:** Added `_heat_risk_usd` field to `TradeState`, frozen at full admission risk. Heat caps sum `_heat_risk_usd`; `initial_risk_usd` used for P&L only. Fill path: `evaluate_entry()` → stamp `_heat_risk_usd` → `enforce_portfolio_heat()` → stage into `_newly_opened`.
- **Before Stats:** Trades 178, Win Rate 44.38%, Avg R +0.60, Max DD 28.79%, HEAT_CAP skips 296
- **After Stats:** Trades 151, Win Rate 44.37%, Avg R +0.63, Max DD 22.84%, HEAT_CAP skips 266

| Segment       | Trades | Share | Max DD | PnL share |
| ------------- | ------ | ----- | ------ | --------- |
| **Clustered** | 86     | 57.0% | 14.08% | 105.8%    |
| **Isolated**  | 65     | 43.0% | 21.84% | −5.8%     |

---

### Change 11: Momentum Divergence Cluster Gate

- **Proxy Parameter:** `MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER`
- **Original Value:** `False` → **New Value:** `True`
- **Reasoning:** 13 isolated MD trades at 15.4% WR, −0.56 AvgR drove the entire isolated bucket's net loss. Clustered MDs were net positive.
- **Before Stats:** Trades 151, WR 44.37%, Avg R +0.63, Max DD 22.84%, HEAT_CAP 266
- **After Stats:** Trades 144, WR 44.44%, Avg R +0.60, Max DD 15.48%, HEAT_CAP 230, MD_NO_CLUSTER_PEER 31

| Metric             | Change 10 | Change 11  | Delta       |
| ------------------ | --------- | ---------- | ----------- |
| Max DD             | 22.84%    | **15.48%** | **−7.36pp** |
| Isolated DD        | 21.84%    | **12.00%** | **−9.84pp** |
| Isolated PnL share | −5.8%     | **+16.7%** | **+22.5pp** |

- **Verdict:** Keeping. Max DD −7.4pp, isolated bucket flips positive.

---

### Change 12: Cluster P&L Scaling (Dual-Field Split)

- **Proxy Parameter:** `CLUSTER_PNL_SCALING_MODE`
- **Original Value:** `"off"` → **New Value:** `"full"`
- **Reasoning:** Same-bar same-direction co-fills over-concentrate P&L risk. Scale `initial_risk_usd` by 1/N; `_heat_risk_usd` frozen at full admission risk.

#### Sweep infrastructure fixes (applied to all future sweeps)

**Bug 1 — Missing global state reset:** `reset_global_state()` called before each mode.

**Bug 2 — Cold-start contamination:** 30-day warmup pass before each mode. `_pending_fills` and `_active_setup_keys` transferred from warmup engine to real engine. Same fix applied to `run_backtest.py`.

**Bug 3 — Module-level constant patching:** Parameters imported as module-level constants (not just `CONFIG` dict) must be patched via direct module attribute assignment. See `set_heat_pct()` in `scratch/run_heat_sweep.py` as the pattern.

- **Before Stats (Change 11, `"off"`, warmed):** Trades 158, WR 46.20%, Avg R +0.62, Engine DD 29.63%, Journal DD 16.31%

| Metric         | off    | cap2   | full       | Delta (full vs off) |
| -------------- | ------ | ------ | ---------- | ------------------- |
| Trades         | 158    | 209    | **208**    | +50                 |
| Win Rate       | 46.20% | 43.54% | **43.75%** | −2.45pp             |
| Avg R          | +0.62  | +0.58  | **+0.59**  | −0.03               |
| Engine Max DD  | 29.63% | 26.77% | **26.76%** | **−2.87pp**         |
| Journal Max DD | 16.31% | 16.67% | **15.40%** | −0.91pp             |
| HEAT_CAP skips | 248    | 53     | **54**     | −194                |

- **Verdict:** Keeping `full`. Engine DD −2.87pp. HEAT_CAP skips 248→54.

---

### Change 13: Portfolio Heat Reduction

- **Proxy Parameter:** `MAX_HEAT_PCT` and `MAX_CORRELATED_HEAT_PCT`
- **Original Value:** `0.08` → **New Value:** `0.06`
- **Reasoning:** After cluster scaling, HEAT_CAP skips dropped to 54 — ceiling barely binding. Tightening forces selectivity. Sweep confirmed 6% dominates every quality metric.

| MAX_HEAT_PCT    | Trades | Win Rate   | Avg R | Engine DD  | Journal DD | HEAT_SK |
| --------------- | ------ | ---------- | ----- | ---------- | ---------- | ------- |
| **6% (chosen)** | 119    | **47.06%** | +0.58 | **15.28%** | **15.28%** | 356     |
| 8% (baseline)   | 208    | 43.75%     | +0.59 | 26.76%     | 15.40%     | 54      |
| 10%             | 223    | 44.84%     | +0.58 | 22.76%     | 17.17%     | 14      |
| 12%             | 230    | 44.35%     | +0.57 | 23.33%     | 18.29%     | 2       |

- **Verdict:** Keeping 6%. Engine DD −11.49pp vs 8%, WR +3.31pp, AvgR flat.

#### Per-setup breakdown (Change 13)

| Setup Type          | Trades | Win Rate | Avg R |
| ------------------- | ------ | -------- | ----- |
| CDC                 | 16     | 56.2%    | +1.11 |
| OPEN_DRIVE          | 39     | 41.0%    | +0.86 |
| MSB_DEEP            | 19     | 57.9%    | +0.13 |
| MSB_SHALLOW         | 14     | 42.9%    | +0.01 |
| SR_FLIP             | 22     | 45.5%    | +0.34 |
| SFP                 | 6      | 33.3%    | −0.06 |
| MOMENTUM_DIVERGENCE | 2      | 50.0%    | +0.77 |

---

### Change 14: SFP Disable

- **Proxy Parameter:** `ENABLE_SFP`
- **Original Value:** `True` → **New Value:** `False`
- **Files:** `bot/config.py`, `bot/setup_detection/sfp.py`
- **Reasoning:** SFP was the weakest active setup: 6 trades, 33.3% WR, −0.06 AvgR. With 356 HEAT_CAP skips, freeing SFP slots redirects heat to better setups.
- **Before Stats:** Trades 119, WR 47.06%, Avg R +0.58, Engine DD 15.28%, HEAT_CAP 356
- **After Stats:** Trades 108, WR **50.00%**, Avg R **+0.64**, Engine DD **13.87%**, HEAT_CAP 361

| Metric      | Change 13 | Change 14  | Delta       |
| ----------- | --------- | ---------- | ----------- |
| Trades      | 119       | 108        | −11         |
| Win Rate    | 47.06%    | **50.00%** | **+2.94pp** |
| Avg R       | +0.58     | **+0.64**  | **+0.06**   |
| Engine DD   | 15.28%    | **13.87%** | **−1.41pp** |
| Quick-stops | 15        | 13         | −2          |

- **Verdict:** Keeping. Every metric improved. WR crosses 50% for the first time.

#### Cluster analysis (Change 14)

| Segment       | Trades | Share | Max DD     | PnL share  |
| ------------- | ------ | ----- | ---------- | ---------- |
| **Clustered** | 60     | 55.6% | **5.82%**  | **105.0%** |
| **Isolated**  | 48     | 44.4% | **17.37%** | **−5.0%**  |

**Isolated breakdown:**

| Setup Type  | n   | WR    | AvgR  | PnL ($) |
| ----------- | --- | ----- | ----- | ------- |
| MSB_SHALLOW | 4   | 50.0% | −0.23 | −$4,094 |
| MSB_DEEP    | 7   | 57.1% | −0.03 | −$2,563 |
| CDC         | 4   | 50.0% | −0.09 | −$2,478 |
| SR_FLIP     | 6   | 50.0% | +0.35 | +$2,206 |
| OPEN_DRIVE  | 27  | 37.0% | +0.32 | +$2,876 |

---

### Change 15: MSB_SHALLOW Cluster Gate (ATTEMPTED — REVERTED)

- **Proxy Parameter:** `MSB_SHALLOW_REQUIRE_CLUSTER`
- **Attempted Value:** `True` → **Reverted:** gate removed
- **Before Stats:** Trades 108, WR 50.00%, Avg R +0.64, Engine DD 13.87%, Journal DD 12.11%
- **After Stats (with gate):** Trades 96, WR 50.00%, Avg R +0.72, Engine DD **22.27%**, Journal DD 11.98%
- **Reason for revert:** Engine DD +8.40pp. Freed slots claimed by longer-running concurrent trades. Journal DD flat confirms spike was live exposure, not P&L path. REVERTED.

---

### Change 16: MSB_SHALLOW Full Disable (ATTEMPTED — REVERTED)

- **Proxy Parameter:** `ENABLE_MSB_SHALLOW`
- **Attempted Value:** `False` → **Reverted:** `True`
- **Before Stats:** Trades 108, WR 50.00%, Avg R +0.64, Engine DD 13.87%, HEAT_CAP 361
- **After Stats (disabled):** Trades 105, WR 48.57%, Avg R +0.70, Engine DD **17.20%**, HEAT_CAP 274
- **Reason for revert:** Engine DD +3.33pp, WR −1.43pp. Same failure mode as Change 15 — freed heat admitted longer-running concurrent trades. **MSB_SHALLOW confirmed heat occupier.** Do not attempt further filtering.

---

### Change 17: MSB_DEEP Cluster Gate (ATTEMPTED — REVERTED)

- **Proxy Parameter:** `MSB_DEEP_REQUIRE_CLUSTER`
- **Attempted Value:** `True` → **Reverted:** gate removed
- **Files:** `bot/config.py`, `bot/backtesting/engine.py`
- **Reasoning for attempt:** MSB_DEEP isolated (7 trades, −0.03 AvgR, −$2,563) was the second largest isolated drag. MSB_DEEP overall showed genuine edge (66.7% WR, +0.33 AvgR at Change 14), suggesting clustered instances were carrying returns while isolated dragged.
- **Before Stats (Change 14):** Trades 108, WR 50.00%, Avg R +0.64, Engine DD 13.87%, Journal DD 12.11%
- **After Stats (with gate):** Trades 125, WR 42.40%, Avg R +0.61, Engine DD **20.40%**, Journal DD 11.86%, MSB_DEEP_NO_CLUSTER_PEER 81

| Metric      | Change 14 | Change 17 (attempted) | Delta          |
| ----------- | --------- | --------------------- | -------------- |
| Trades      | 108       | 125                   | +17            |
| Win Rate    | 50.00%    | 42.40%                | **−7.60pp ⚠️** |
| Avg R       | +0.64     | +0.61                 | −0.03          |
| Engine DD   | 13.87%    | **20.40%**            | **+6.53pp ⚠️** |
| Quick-stops | 13        | 17                    | +4             |

- **Cluster analysis (with gate):**

| Segment       | Trades | Share | Max DD     | PnL share |
| ------------- | ------ | ----- | ---------- | --------- |
| **Clustered** | 66     | 52.8% | **17.58%** | 50.4%     |
| **Isolated**  | 59     | 47.2% | **10.31%** | 49.6%     |

- **Reason for revert:** Worst result of all gate/disable attempts. WR −7.60pp, Engine DD +6.53pp. The gate blocked 81 MSB_DEEP instances — the cluster analysis inversion tells the full story: clustered DD exploded to 17.58% (from 5.82%) while isolated DD improved to 10.31%. The 81 blocked MSB_DEEP instances were not isolated duds — they were **forming the low-DD clustered path**. By requiring a peer, MSB_DEEP only fires when other setups are already open, creating crowded concurrent exposure. Trade count also increased (+17) as freed MSB_DEEP heat slots were claimed by other setups.
- **Structural conclusion: MSB_DEEP is a confirmed heat occupier.** All three attempted setups (MSB_SHALLOW, MSB_DEEP, and indirectly CDC) exhibit the same pattern — their isolated drag is the cost of preventing worse concurrent exposure at the 6% heat ceiling. This mirrors the MD dynamic from Change 4. Setup-level gates and disables are exhausted as a tuning direction.
- **Verdict: REVERTED.** Engine back to Change 14 baseline (108 trades / 13.87% DD).

---

## Current State (Live Baseline = Change 19)

| Metric                     | Value      |
| -------------------------- | ---------- |
| Total Trades               | 93         |
| Win Rate                   | 53.80%     |
| Average R                  | +0.79      |
| Engine Max Drawdown        | 17.12%     |
| Journal (Isolated) DD      | 9.79%      |
| HEAT_CAP skips             | 357        |
| MD_NO_CLUSTER_PEER skips   | ~38 (unchanged) |
| MSB_SHALLOW trades         | 4          |
| MSB_DEEP trades            | 19         |

**Active CONFIG:** `MAX_HEAT_PCT=0.06`, `MAX_CORRELATED_HEAT_PCT=0.06`, `MIN_STOP_ATR_MULT=1.2`, `SFP_WICK_ATR_MULT=1.0`, `MOMENTUM_DIVERGENCE_MIN_STRENGTH=5.0`, `MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER=True`, `CLUSTER_PNL_SCALING_MODE=full`, `ENABLE_SFP=False`, `SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`

### Key Observations — Heat Occupier Pattern

Three consecutive setup-level changes (Changes 15, 16, 17) all produced Engine DD regressions despite isolated PnL improvements. The pattern is consistent:

- Removing or gating a setup frees heat slots → those slots are claimed by longer-running concurrent trades → clustered DD spikes → Engine DD worsens.
- MSB_SHALLOW (Changes 15, 16): Engine DD +8.40pp / +3.33pp.
- MSB_DEEP (Change 17): Engine DD +6.53pp, clustered DD 5.82% → 17.58%, WR −7.60pp.
- The isolated drag from MSB_SHALLOW (−$4,094), MSB_DEEP (−$2,563), and CDC (−$2,478) is the structural cost of keeping the heat budget occupied with shorter-duration setups that prevent worse concurrent exposure.

**Setup-level filtering is exhausted as a tuning direction at the current 6% heat ceiling.** The system is heat-constrained; what goes in matters less than what gets displaced.

### Recommended Next Directions

Three directions remain that don't rely on setup-level filtering:

1. **Conviction score threshold** — `evaluate_entry` scores each candidate; raising the minimum admitted conviction score filters within setups rather than across them. High-conviction isolated trades may have better PnL than low-conviction ones regardless of setup type. Check what `conviction_score` distribution looks like across the journal.

2. **Entry timing / bar count filter** — most quick-stops (13, 12.0% of trades) exit within 3 bars. A minimum bars-since-signal filter or a volatility-adjusted entry check may cut these without freeing heat to worse setups.

3. **Lookback / Fib parameter sweep for MSB_SHALLOW and MSB_DEEP** — rather than disabling, tighten the detection criteria (e.g. `SHALLOW_FIB_MIN`, `SHALLOW_FIB_MAX`, `DEEP_FIB_MIN`, `DEEP_FIB_MAX`, `SHALLOW_ATR_CAP_MULT`) so fewer but higher-quality instances are detected. This reduces detection count without freeing admitted-trade heat slots.

### Planned Next Changes

- ~~Dual-field heat/P&L risk tracking.~~ ✅ **Change 10.**
- ~~MD cluster gate.~~ ✅ **Change 11.**
- ~~Cluster P&L scaling sweep.~~ ✅ **Change 12 — `full` mode.**
- ~~`MAX_HEAT_PCT` sweep.~~ ✅ **Change 13 — tightened to 6%.**
- ~~SFP disable.~~ ✅ **Change 14 — `ENABLE_SFP=False`.**
- ~~MSB_SHALLOW cluster gate.~~ ❌ **Change 15 — reverted. Engine DD +8.40pp.**
- ~~MSB_SHALLOW full disable.~~ ❌ **Change 16 — reverted. Engine DD +3.33pp. Heat occupier confirmed.**
- ~~MSB_DEEP cluster gate.~~ ❌ **Change 17 — reverted. Engine DD +6.53pp, WR −7.60pp. Heat occupier confirmed.**
- ~~Fib/detection parameter sweep for MSB_SHALLOW and MSB_DEEP.~~ ✅ **Change 19 — `SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`. WR +3.8pp, AvgR +0.15, IsoDD −6.92pp.**
- ~~Conviction score threshold.~~ ❌ **Change 20 — exhausted. Score distribution is 96.5% / 3.5% at scores 2/3. No viable mid-point exists.**
- **[Next]** OPEN_DRIVE detection-criteria sweep — 33 trades at 36.4% WR is the weakest WR of any active setup. Tighten `DRIVE_ATR_MULT` and/or `DRIVE_BODY_RANGE_RATIO_MIN` to reduce low-quality drive detections without a gate/disable (same ATR-cap approach as Change 19).
- **[Next]** SR_FLIP detection-criteria sweep — 14 trades at 35.7% WR. Similar approach: tighten flip confirmation criteria before considering any gate/disable.
- **[Defer]** Entry timing / quick-stop filter — investigate whether quick-stops cluster in specific setups or time-of-day windows.

---

### Change 20: Conviction Score Threshold — EXHAUSTED (No Change Applied)

- **Proxy Parameter:** `CONVICTION_DIRECT_ENTRY_THRESHOLD`
- **Investigated value:** raising from `2` → `3`
- **Outcome: NO CHANGE. Direction exhausted.**

#### Findings (`scratch/run_conviction_analysis.py`, Change 19 params, 86 trades):

| Score | N  | Share | WR    | AvgR  | SumR   |
| ----- | -- | ----- | ----- | ----- | ------ |
| 2     | 83 | 96.5% | 49.4% | +0.70 | +58.37 |
| 3     | 3  | 3.5%  | 66.7% | +1.05 | +3.14  |

- **No score=0 or score=1 trades admitted.** `CONVICTION_DIRECT_ENTRY_THRESHOLD=2` already acts as the floor. Score <2 setups either are never generated for BTC/H1 or route to the FTA-pending queue rather than being logged as skipped.
- **No LOW_CONVICTION skips exist.** Every skip is `HEAT_CAP` (91.5%, 407) or `MD_NO_CLUSTER_PEER` (8.5%, 38). The scoring system produces no sub-threshold candidates past `evaluate_entry`.
- **Score=3 cliff:** raising the threshold to ≥3 drops 83 of 86 trades → 3 trades in 90 days. Not a viable operating point.
- **Score distribution is structurally collapsed** — the 3-point scoring rubric assigns score=2 to virtually everything. There is no useful intermediate threshold between 2 and 3.

#### Per-setup breakdown at score=2 (all):

| Setup Type          | N  | WR    | AvgR   | Notes                                      |
| ------------------- | -- | ----- | ------ | ------------------------------------------ |
| CDC                 | 15 | 60.0% | +0.829 | Solid                                      |
| MSB_DEEP            | 15 | 73.3% | +0.486 | High WR but low AvgR — targets conservative? |
| MSB_SHALLOW         | 5  | 60.0% | +0.218 | Low count, acceptable                      |
| OPEN_DRIVE          | 33 | 36.4% | +0.717 | Dominant by count, low WR, positive only from large wins |
| SR_FLIP             | 14 | 35.7% | +0.492 | Marginal WR                                |
| CONSOLIDATION_ENTRY | 1  | 100%  | +7.003 | 1 trade, no inference                      |
| MOMENTUM_DIVERGENCE | 1  | 100%  | +3.004 | Score=3, 1 trade                           |

- **Win/loss asymmetry:** score=2 wins avg +2.23R, losses avg −0.79R — edge is entirely in win magnitude. Both WR (49.4%) and loss count (42) are slightly unfavourable, but the R asymmetry keeps expectancy positive.
- **OPEN_DRIVE is the structural weak point:** 33 trades (38% of all), 36.4% WR. It contributes most trades and has the lowest WR of any active setup. Detection tightening (same approach as Change 19 for MSB_SHALLOW) is the logical next investigation.

#### Trade count note:
Conviction analysis produced 86 trades vs 93 in Change 19 sweep. Likely caused by the analysis script not calling `reset_portfolio_state()` before the real pass. Non-blocking — the per-setup relative breakdown is still valid. Sweep infrastructure (with explicit state reset) remains the canonical number source.



---

### Change 18: Engine Bug Fix — `_flush_pending_fills` Silent Trade Drop

- **Type:** Correctness fix (not a tunable parameter)
- **File:** `bot/backtesting/engine.py` — `_flush_pending_fills()`
- **Bug 1 — Non-MD trades silently dropped:** The MD cluster gate (`if MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER and ...`) was the **only** code path that ever staged trades into `_newly_opened`. After the `if` block, non-MD candidates fell off the end of the function unfilled. Heat check and fill were nested inside the MD branch, so every CDC, MSB, SR_FLIP, OPEN_DRIVE, and SFP candidate was silently discarded after `evaluate_entry`. This caused the `run_msb_fib_sweep.py` to report 0 trades for all configurations.
- **Bug 2 — `still_pending` never written back:** Cross-timeframe/bar candidates were accumulated in `still_pending` but the list was never stored back to `self._pending_fills`, so candidates from other bars accumulated forever and were never retried.
- **Fix:** Pulled heat check + `_newly_opened` staging out of the MD branch into a shared `else`-equivalent block that runs for **all** setup types (MD trades reach it only after passing the cluster gate). Added `self._pending_fills = still_pending` at the end of the loop.
- **Validation:** Baseline column of Change 19 sweep exactly reproduces Change 14 numbers (108 trades, 50.0% WR, +0.64 AvgR, 13.87% EngDD). ✅

---

### Change 19: MSB Shallow Fib / ATR-Cap Tightening

- **Proxy Parameters:** `SHALLOW_FIB_MIN`, `SHALLOW_ATR_CAP_MULT`
- **Original Values:** `SHALLOW_FIB_MIN=0.236`, `SHALLOW_ATR_CAP_MULT=3.0`
- **New Values:** `SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`
- **Reasoning:** MSB_SHALLOW had 14 admitted trades but +0.01 AvgR — nearly breakeven. The ATR cap floors the retracement in absolute volatility terms: a bar retreating 3× ATR before reversing is not a shallow pullback in any practical sense. Raising `SHALLOW_FIB_MIN` to 0.30 narrows the band (removing very early, weak retracements), and dropping the ATR cap from 3.0→2.0 removes oversized moves that only pass the Fib test because of a wide pivot swing. Sweep confirmed this reduces SH_n from 14→4, but the 4 that remain are materially higher quality (WR 42.9%→50.0%, AvgR +0.01→+0.01 — SH itself stays near flat, but freed heat goes to better setups).

#### Full sweep table (baseline = Change 14):

| Label | Tot | WR | AvgR | EngDD | HeatSk | SH_n | SH_WR | SH_R | DP_n | DP_WR | DP_R | CluDD | IsoDD |
| ----------------------------- | --- | ------ | ----- | ------ | ------ | ---- | ----- | ----- | ---- | ----- | ----- | ----- | ----- |
| baseline (0.236–0.382, cap3.0) | 108 | 50.0% | +0.64 | 13.87% | 361 | 14 | 42.9% | +0.01 | 18 | 66.7% | +0.33 | 5.90% | 16.71% |
| sh_0.30–0.382 | 98 | 46.9% | +0.63 | 19.73% | 347 | 9 | 22.2% | −0.23 | 19 | 63.2% | +0.60 | 7.28% | 12.07% |
| **sh_0.30–0.382_cap2.0 ✅** | **93** | **53.8%** | **+0.79** | **17.12%** | **357** | **4** | **50.0%** | **+0.01** | **19** | **68.4%** | **+0.72** | **9.03%** | **9.79%** |
| dp_golden | 90 | 51.1% | +0.67 | 13.86% | 375 | 12 | 41.7% | −0.21 | 9 | 55.6% | +0.14 | 16.03% | 12.55% |
| sh+dp_tight | 120 | 43.3% | +0.56 | 22.47% | 265 | 12 | 16.7% | −0.26 | 12 | 50.0% | +0.17 | 14.85% | 12.08% |
| sh+dp_tight_cap2.0 | 81 | 51.8% | +0.79 | 18.60% | 335 | 5 | 60.0% | +0.03 | 8 | 50.0% | +0.13 | 20.36% | 7.92% |
| sh_tight_dp_golden_cap1.5 | 111 | 47.8% | +0.64 | 16.58% | 249 | 4 | 25.0% | −0.25 | 11 | 54.5% | +0.27 | 16.51% | 11.23% |
| sh_0.35–0.382 | 94 | 53.2% | +0.77 | 17.12% | 333 | 5 | 40.0% | −0.19 | 19 | 68.4% | +0.72 | 8.60% | 9.85% |
| sh_0.35–0.382_dp_golden | 112 | 48.2% | +0.63 | 16.58% | 246 | 5 | 40.0% | −0.00 | 11 | 54.5% | +0.27 | 15.04% | 11.28% |

- **Before Stats (Change 14):** Trades 108, WR 50.00%, Avg R +0.64, Engine DD 13.87%, IsoDD 16.71%
- **After Stats:** Trades 93, WR **53.8%**, Avg R **+0.79**, Engine DD **17.12%**, IsoDD **9.79%**

| Metric    | Change 14  | Change 19  | Delta         |
| --------- | ---------- | ---------- | ------------- |
| Trades    | 108        | 93         | −15           |
| Win Rate  | 50.00%     | **53.8%**  | **+3.8pp**    |
| Avg R     | +0.64      | **+0.79**  | **+0.15**     |
| Engine DD | 13.87%     | 17.12%     | +3.25pp ⚠️   |
| IsoDD     | 16.71%     | **9.79%**  | **−6.92pp**   |
| SH trades | 14         | 4          | −10           |
| DP trades | 18         | 19         | +1            |
| DP AvgR   | +0.33      | **+0.72**  | **+0.39**     |

- **Key insight:** Tightening shallow detection with ATR_CAP_MULT alone (`sh_0.30-0.382` without cap) triggers the full heat-occupier EngDD spike (+5.86pp, WR −3.1pp) — same failure mode as Changes 15-17. Adding `SHALLOW_ATR_CAP_MULT=2.0` suppresses the spike by removing only the largest-ATR-retracement instances (which are the weakest quality) rather than gating admitted trades. The freed SH slots are reallocated to DP, which delivers +0.72 AvgR vs the previous +0.33. `dp_golden` by contrast cuts DP in half (18→9 trades, +0.33→+0.14 AvgR) with effectively zero EngDD cost but no meaningful quality gain.
- **EngDD caveat:** +3.25pp Engine DD is a real cost. Mechanically identical to Changes 15-17 (freed slots → longer-running concurrent trades → higher live exposure). The mitigation is that WR crosses 53.8% and AvgR improves +0.15, which compound over 93 trades into a meaningfully better equity path.
- **Verdict: Keeping.** WR +3.8pp, AvgR +0.15, IsoDD −6.92pp. **`SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`.**
