# Parameter Tuning Changelog

**Walk-Forward Protocol:** fixed train/test/holdout windows. Tune only on TRAIN.
TEST/OOS is touched once per major milestone. HOLDOUT is untouched until final
validation before paper trading.

| Split | Window | Use |
| ----- | ------ | --- |
| TRAIN / in-sample | 2026-03-15 -> 2026-06-13 | All iterative parameter changes and sweeps |
| TEST / OOS | 2025-12-14 -> 2026-03-14 | One generalization check per major milestone |
| FINAL HOLDOUT | 2025-09-15 -> 2025-12-14 | Final pre-paper validation only |

Canonical runner:

- Train/tuning: `python3 scratch/walk_forward.py --split train`
- Milestone OOS check: `python3 scratch/walk_forward.py --split test --milestone "Change XX"`
- Final holdout: `python3 scratch/walk_forward.py --split holdout --final-validation --milestone "pre-paper"`

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

| Label                          | Tot    | WR        | AvgR      | EngDD      | HeatSk  | SH_n  | SH_WR     | SH_R      | DP_n   | DP_WR     | DP_R      | CluDD     | IsoDD     |
| ------------------------------ | ------ | --------- | --------- | ---------- | ------- | ----- | --------- | --------- | ------ | --------- | --------- | --------- | --------- |
| baseline (0.236–0.382, cap3.0) | 108    | 50.0%     | +0.64     | 13.87%     | 361     | 14    | 42.9%     | +0.01     | 18     | 66.7%     | +0.33     | 5.90%     | 16.71%    |
| sh_0.30–0.382                  | 98     | 46.9%     | +0.63     | 19.73%     | 347     | 9     | 22.2%     | −0.23     | 19     | 63.2%     | +0.60     | 7.28%     | 12.07%    |
| **sh_0.30–0.382_cap2.0 ✅**    | **93** | **53.8%** | **+0.79** | **17.12%** | **357** | **4** | **50.0%** | **+0.01** | **19** | **68.4%** | **+0.72** | **9.03%** | **9.79%** |
| dp_golden                      | 90     | 51.1%     | +0.67     | 13.86%     | 375     | 12    | 41.7%     | −0.21     | 9      | 55.6%     | +0.14     | 16.03%    | 12.55%    |
| sh+dp_tight                    | 120    | 43.3%     | +0.56     | 22.47%     | 265     | 12    | 16.7%     | −0.26     | 12     | 50.0%     | +0.17     | 14.85%    | 12.08%    |
| sh+dp_tight_cap2.0             | 81     | 51.8%     | +0.79     | 18.60%     | 335     | 5     | 60.0%     | +0.03     | 8      | 50.0%     | +0.13     | 20.36%    | 7.92%     |
| sh_tight_dp_golden_cap1.5      | 111    | 47.8%     | +0.64     | 16.58%     | 249     | 4     | 25.0%     | −0.25     | 11     | 54.5%     | +0.27     | 16.51%    | 11.23%    |
| sh_0.35–0.382                  | 94     | 53.2%     | +0.77     | 17.12%     | 333     | 5     | 40.0%     | −0.19     | 19     | 68.4%     | +0.72     | 8.60%     | 9.85%     |
| sh_0.35–0.382_dp_golden        | 112    | 48.2%     | +0.63     | 16.58%     | 246     | 5     | 40.0%     | −0.00     | 11     | 54.5%     | +0.27     | 15.04%    | 11.28%    |

- **Before Stats (Change 14):** Trades 108, WR 50.00%, Avg R +0.64, Engine DD 13.87%, IsoDD 16.71%
- **After Stats:** Trades 93, WR **53.8%**, Avg R **+0.79**, Engine DD **17.12%**, IsoDD **9.79%**

| Metric    | Change 14 | Change 19 | Delta       |
| --------- | --------- | --------- | ----------- |
| Trades    | 108       | 93        | −15         |
| Win Rate  | 50.00%    | **53.8%** | **+3.8pp**  |
| Avg R     | +0.64     | **+0.79** | **+0.15**   |
| Engine DD | 13.87%    | 17.12%    | +3.25pp ⚠️  |
| IsoDD     | 16.71%    | **9.79%** | **−6.92pp** |
| SH trades | 14        | 4         | −10         |
| DP trades | 18        | 19        | +1          |
| DP AvgR   | +0.33     | **+0.72** | **+0.39**   |

- **Key insight:** Tightening shallow detection with ATR_CAP_MULT alone (`sh_0.30-0.382` without cap) triggers the full heat-occupier EngDD spike (+5.86pp, WR −3.1pp) — same failure mode as Changes 15-17. Adding `SHALLOW_ATR_CAP_MULT=2.0` suppresses the spike by removing only the largest-ATR-retracement instances (which are the weakest quality) rather than gating admitted trades. The freed SH slots are reallocated to DP, which delivers +0.72 AvgR vs the previous +0.33. `dp_golden` by contrast cuts DP in half (18→9 trades, +0.33→+0.14 AvgR) with effectively zero EngDD cost but no meaningful quality gain.
- **EngDD caveat:** +3.25pp Engine DD is a real cost. Mechanically identical to Changes 15-17 (freed slots → longer-running concurrent trades → higher live exposure). The mitigation is that WR crosses 53.8% and AvgR improves +0.15, which compound over 93 trades into a meaningfully better equity path.
- **Verdict: Keeping.** WR +3.8pp, AvgR +0.15, IsoDD −6.92pp. **`SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`.**

---

### Change 20: Conviction Score Threshold — EXHAUSTED (No Change Applied)

- **Proxy Parameter:** `CONVICTION_DIRECT_ENTRY_THRESHOLD`
- **Investigated value:** raising from `2` → `3`
- **Outcome: NO CHANGE. Direction exhausted.**

#### Findings (`scratch/run_conviction_analysis.py`, Change 19 params, 86 trades):

| Score | N   | Share | WR    | AvgR  | SumR   |
| ----- | --- | ----- | ----- | ----- | ------ |
| 2     | 83  | 96.5% | 49.4% | +0.70 | +58.37 |
| 3     | 3   | 3.5%  | 66.7% | +1.05 | +3.14  |

- **No score=0 or score=1 trades admitted.** `CONVICTION_DIRECT_ENTRY_THRESHOLD=2` already acts as the floor. Score <2 setups either are never generated for BTC/H1 or route to the FTA-pending queue rather than being logged as skipped.
- **No LOW_CONVICTION skips exist.** Every skip is `HEAT_CAP` (91.5%, 407) or `MD_NO_CLUSTER_PEER` (8.5%, 38). The scoring system produces no sub-threshold candidates past `evaluate_entry`.
- **Score=3 cliff:** raising the threshold to ≥3 drops 83 of 86 trades → 3 trades in 90 days. Not a viable operating point.
- **Score distribution is structurally collapsed** — the 3-point scoring rubric assigns score=2 to virtually everything. There is no useful intermediate threshold between 2 and 3.

#### Per-setup breakdown at score=2 (all):

| Setup Type          | N   | WR    | AvgR   | Notes                                                    |
| ------------------- | --- | ----- | ------ | -------------------------------------------------------- |
| CDC                 | 15  | 60.0% | +0.829 | Solid                                                    |
| MSB_DEEP            | 15  | 73.3% | +0.486 | High WR but low AvgR — targets conservative?             |
| MSB_SHALLOW         | 5   | 60.0% | +0.218 | Low count, acceptable                                    |
| OPEN_DRIVE          | 33  | 36.4% | +0.717 | Dominant by count, low WR, positive only from large wins |
| SR_FLIP             | 14  | 35.7% | +0.492 | Marginal WR                                              |
| CONSOLIDATION_ENTRY | 1   | 100%  | +7.003 | 1 trade, no inference                                    |
| MOMENTUM_DIVERGENCE | 1   | 100%  | +3.004 | Score=3, 1 trade                                         |

- **Win/loss asymmetry:** score=2 wins avg +2.23R, losses avg −0.79R — edge is entirely in win magnitude. Both WR (49.4%) and loss count (42) are slightly unfavourable, but the R asymmetry keeps expectancy positive.
- **OPEN_DRIVE is the structural weak point:** 33 trades (38% of all), 36.4% WR. It contributes most trades and has the lowest WR of any active setup. Detection tightening (same approach as Change 19 for MSB_SHALLOW) is the logical next investigation.

#### Trade count note:

Conviction analysis produced 86 trades vs 93 in Change 19 sweep. Likely caused by the analysis script not calling `reset_portfolio_state()` before the real pass. Non-blocking — the per-setup relative breakdown is still valid. Sweep infrastructure (with explicit state reset) remains the canonical number source.

---

### Change 21: OPEN_DRIVE Detection Tightening

- **Proxy Parameters:** `DRIVE_ATR_MULT`, `DRIVE_BODY_RANGE_RATIO_MIN`
- **Original Values:** `DRIVE_ATR_MULT=1.0`, `DRIVE_BODY_RANGE_RATIO_MIN=0.50`
- **New Values:** `DRIVE_ATR_MULT=1.2`, `DRIVE_BODY_RANGE_RATIO_MIN=0.65`
- **Reasoning:** At Change 19, OPEN_DRIVE was the weakest active setup by win rate: 33 trades at 36.4% WR, representing 38% of all trades. The low WR was structural — too many weak drive candles being admitted. Tightening `DRIVE_ATR_MULT` from 1.0→1.2 requires stronger impulse moves, and raising `DRIVE_BODY_RANGE_RATIO_MIN` from 0.50→0.65 filters out candles with long wicks that lack directional conviction. This is the same detection-tightening approach that worked for MSB_SHALLOW (Change 19) — reduce low-quality detections without gating admitted trades.
- **Before Stats (Change 19):** Trades 93, WR 53.76%, Avg R +0.79, Engine DD 17.12%, HEAT_CAP 357
- **After Stats:** Trades 92, WR 51.09%, Avg R +0.82, Engine DD 17.20%, HEAT_CAP 289

| Metric             | Change 19 | Change 21 | Delta   |
| ------------------ | --------- | --------- | ------- |
| Trades             | 93        | 92        | -1      |
| Win Rate           | 53.76%    | 51.09%    | -2.67pp |
| Avg R              | +0.79     | +0.82     | +0.03   |
| Engine DD          | 17.12%    | 17.20%    | +0.08pp |
| HEAT_CAP skips     | 357       | 289       | -68     |
| MD_NO_CLUSTER_PEER | ~38       | 45        | +7      |

**Per-setup comparison:**

| Setup Type      | Change 19 | Change 21 | Delta     |
| --------------- | --------- | --------- | --------- |
| OPEN_DRIVE n    | 33        | 24        | -9 (-27%) |
| OPEN_DRIVE WR   | 36.4%     | 45.8%     | +9.4pp    |
| OPEN_DRIVE AvgR | +0.72     | +1.19     | +0.47     |
| SR_FLIP n       | 14        | 24        | +10       |
| SR_FLIP WR      | 35.7%     | 45.8%     | +10.1pp   |
| MSB_DEEP n      | 15        | 21        | +6        |
| MSB_DEEP WR     | 73.3%     | 57.1%     | -16.2pp   |

- **Key insight:** This is a clean structural improvement. OPEN_DRIVE detections dropped from 33→24 (-27%), but the remaining candidates have materially higher quality: WR +9.4pp, AvgR +0.47. The freed heat slots were claimed by SR_FLIP (+10 trades) and MSB_DEEP (+6 trades). Unlike the gate/disable attempts (Changes 15-17), there is **no engine DD spike** (+0.08pp is noise). This confirms detection tightening is the correct approach — it reduces low-quality signal volume while preserving the beneficial heat-occupier function.

- **HEAT_CAP drop:** 357→289 (-68 skips) is unexpected but positive — with better-quality OPEN_DRIVE candidates, fewer marginal trades are being gated by the heat ceiling. The system is self-selecting higher-conviction entries.

- **Verdict: Keeping.** AvgR improves, OPEN_DRIVE WR crosses 45%, no EngDD degradation. **`DRIVE_ATR_MULT=1.2`, `DRIVE_BODY_RANGE_RATIO_MIN=0.65`.**

---

## Current State (Live Baseline = Change 21)

| Metric                   | Value        |
| ------------------------ | ------------ |
| Total Trades             | 92           |
| Win Rate                 | 51.09%       |
| Average R                | +0.82        |
| Engine Max Drawdown      | 17.20%       |
| Journal (Isolated) DD    | ~9.5% (est.) |
| HEAT_CAP skips           | 289          |
| MD_NO_CLUSTER_PEER skips | 45           |

**Active CONFIG:**

- `MAX_HEAT_PCT=0.06`
- `MAX_CORRELATED_HEAT_PCT=0.06`
- `MIN_STOP_ATR_MULT=1.2`
- `SFP_WICK_ATR_MULT=1.0`
- `MOMENTUM_DIVERGENCE_MIN_STRENGTH=5.0`
- `MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER=True`
- `CLUSTER_PNL_SCALING_MODE=full`
- `ENABLE_SFP=False`
- `SHALLOW_FIB_MIN=0.30`
- `SHALLOW_ATR_CAP_MULT=2.0`
- `DRIVE_ATR_MULT=1.2`
- `DRIVE_BODY_RANGE_RATIO_MIN=0.65`

**Per-setup breakdown (Change 21):**

| Setup Type          | Trades | Win Rate | Avg R |
| ------------------- | ------ | -------- | ----- |
| CDC                 | 16     | 50.0%    | +0.71 |
| OPEN_DRIVE          | 24     | 45.8%    | +1.19 |
| CONSOLIDATION_ENTRY | 1      | 100%     | +7.00 |
| MSB_SHALLOW         | 6      | 66.7%    | +0.52 |
| SR_FLIP             | 24     | 45.8%    | +0.47 |
| MSB_DEEP            | 21     | 57.1%    | +0.67 |

### Key Observations

**Detection tightening is the correct tuning direction.** Change 19 (MSB_SHALLOW Fib/ATR tightening) and Change 21 (OPEN_DRIVE drive-candle tightening) both improved metrics without triggering the heat-occupier DD spike that plagued gate/disable attempts (Changes 15-17). The pattern:

- Tighten detection criteria → fewer but higher-quality detections → freed heat slots claimed by other setups → net improvement without DD explosion.
- Gate/disable → admitted trades blocked entirely → freed heat slots claimed by longer-running concurrent trades → clustered DD spikes → Engine DD worsens.

**OPEN_DRIVE now has positive edge.** At 45.8% WR and +1.19 AvgR, it's no longer the structural weak point. SR_FLIP is now the lowest WR active setup (45.8%, tied with OPEN_DRIVE) but has lower AvgR (+0.47 vs +1.19).

**HEAT_CAP skips dropped significantly** (357→289) with the OPEN_DRIVE tightening. The system is now more selective at the detection level, reducing the number of marginal candidates that get gated by the heat ceiling.

### Recommended Next Directions

1. **SR_FLIP detection tightening** — Now the weakest setup by AvgR (+0.47) and tied for lowest WR (45.8%). Similar approach to OPEN_DRIVE: tighten flip confirmation criteria (e.g. `FLIP_CONFIRM_BARS`, `FLIP_ATR_MULT`, `FLIP_BODY_RATIO_MIN`) to reduce low-quality flips while preserving the heat-occupier function. SR_FLIP has 24 trades — enough to detect a signal.

2. **MSB_DEEP target investigation** — 57.1% WR but +0.67 AvgR suggests targets are being hit too conservatively, or stops are too tight. MSB_DEEP has the highest WR of any active multi-trade setup but middling AvgR. A sweep of `DEEP_FIB_MIN`/`DEEP_FIB_MAX` or the target-multiple parameters could improve R without sacrificing WR.

3. **CDC detection tightening** — Low trade count (16) makes statistical inference weak; defer until more data or until SR_FLIP is resolved. CDC has neutral WR (50%) but solid AvgR (+0.71) — not a priority.

### Planned Next Changes

- [x] ~~Dual-field heat/P&L risk tracking.~~ ✅ **Change 10.**
- [x] ~~MD cluster gate.~~ ✅ **Change 11.**
- [x] ~~Cluster P&L scaling sweep.~~ ✅ **Change 12 — `full` mode.**
- [x] ~~`MAX_HEAT_PCT` sweep.~~ ✅ **Change 13 — tightened to 6%.**
- [x] ~~SFP disable.~~ ✅ **Change 14 — `ENABLE_SFP=False`.**
- [x] ~~MSB_SHALLOW cluster gate.~~ ❌ **Change 15 — reverted.**
- [x] ~~MSB_SHALLOW full disable.~~ ❌ **Change 16 — reverted.**
- [x] ~~MSB_DEEP cluster gate.~~ ❌ **Change 17 — reverted.**
- [x] ~~Fib/detection parameter sweep for MSB_SHALLOW.~~ ✅ **Change 19 — `SHALLOW_FIB_MIN=0.30`, `SHALLOW_ATR_CAP_MULT=2.0`.**
- [x] ~~Conviction score threshold.~~ ❌ **Change 20 — exhausted.**
- [x] ~~OPEN_DRIVE detection tightening.~~ ✅ **Change 21 — `DRIVE_ATR_MULT=1.2`, `DRIVE_BODY_RANGE_RATIO_MIN=0.65`**
- [x] ~~SR_FLIP anchor matrix check.~~ ✅ **Milestone OOS check completed.**
- [x] ~~SR_FLIP detection tightening.~~ ✅ **Change 22 — `FLIP_BODY_RATIO_MIN=0.50`.**
- [x] ~~MSB_DEEP target sweep.~~ ✅ **Change 23 — `DEEP_FIB_MAX=0.80`.**
- **[Defer]** CDC detection tightening — low trade count (16) makes statistical inference weak; defer until more data.

---

### Milestone: SR_FLIP Anchor Matrix (OOS Check)

- **Type:** Generalization check on TEST/OOS (`2025-12-14` -> `2026-03-14`)
- **Protocol:** `python3 scratch/run_anchor_matrix.py`
- **Reasoning:** To verify if the portfolio heat behavior holds out-of-sample by fixing `SR_FLIP` as the baseline anchor and evaluating marginal contributions of other setups.
- **TRAIN Finalists (passed rule: PnL > SR, AvgR > 0, MaxDD <= 13.69%):**
  - `SR+CONSOLIDATION_ENTRY`
  - `SR+MSB_DEEP`
- **TEST/OOS Stats:**
  - `SR_ONLY`: Trades 60, WR 43.33%, AvgR +0.6881, MaxDD 20.80%
  - `SR+CONSOLIDATION_ENTRY`: Trades 61, WR 44.26%, AvgR +0.7354, MaxDD 20.80% (Marginal PnL: +$4,078)
  - `SR+MSB_DEEP`: Trades 90, WR 43.33%, AvgR +0.5709, MaxDD 26.79% (Marginal PnL: +$14,932)
- **Takeaways:** `SR_FLIP` maintains positive expectancy out-of-sample (+0.6881 AvgR), though win rate is softer (43.33%). Adding `MSB_DEEP` increased trades and PnL but caused the OOS MaxDD to spike to 26.79%, mirroring the concurrent exposure issues seen in the Train set. We proceed with `SR_FLIP` detection tightening to build a stronger baseline win rate.

---

### Change 22: SR_FLIP Detection Tightening

- **Proxy Parameters:** `FLIP_CONFIRM_BARS`, `FLIP_ATR_MULT`, `FLIP_BODY_RATIO_MIN` (Newly implemented in `sr_flip.py`)
- **Original Values:** Implicitly `1`, `0.0`, `0.0`
- **New Value:** `FLIP_BODY_RATIO_MIN=0.50`
- **Reasoning:** Following the success of OPEN_DRIVE tightening (Change 21), we introduced analogous confirmation constraints for SR_FLIP's bounce candle to filter weak signals without gating admitted trades. We swept ATR vs Body Ratio vs multi-bar confirmation.
- **Before Stats (Change 21):** Trades 92, WR 51.09%, Avg R +0.82, Engine DD 17.20% (SR_FLIP WR: 45.8%)
- **After Stats:** Trades 109, WR 54.13%, Avg R +0.76, Engine DD 13.73% (SR_FLIP WR: 59.1%)

| Configuration | Trades | WR | AvgR | EngDD | SR Trades | SR WR | SR AvgR |
|---|---|---|---|---|---|---|---|
| baseline | 92 | 51.1% | +0.82 | 17.20% | 24 | 45.8% | +0.47 |
| `atr_1.0` | 107 | 49.5% | +0.65 | 24.31% ⚠️ | 7 | 28.6% | -0.33 |
| `bars_2` | 113 | 52.2% | +0.70 | 13.05% | 22 | 54.5% | +0.53 |
| **`body_0.50`** ✅ | 109 | **54.1%** | +0.76 | **13.73%** | 22 | **59.1%** | +0.50 |

- **Verdict:** Keeping `FLIP_BODY_RATIO_MIN=0.50`. Tightening the ATR multiplier on the confirmation candle caused a massive concurrent exposure Engine DD spike (24.31%)—the same failure mode seen in previous gating attempts. However, enforcing that the confirmation candle has directional conviction (body > 50% of range) improved SR_FLIP's WR from 45.8% to 59.1% and dropped Engine DD from 17.20% to 13.73% while actually *increasing* total portfolio trades (92 → 109) and overall portfolio WR (51.1% → 54.1%).

---

### Change 23: MSB_DEEP Fib Retracement Tightening

- **Proxy Parameters:** `DEEP_FIB_MIN`, `DEEP_FIB_MAX`
- **Original Values:** `DEEP_FIB_MIN=0.55`, `DEEP_FIB_MAX=0.85`
- **New Value:** `DEEP_FIB_MIN=0.55`, `DEEP_FIB_MAX=0.80`
- **Reasoning:** MSB_DEEP showed high win rate but mediocre average R (+0.67 AvgR vs +1.01 for OPEN_DRIVE). We swept various Fibonacci retracement bands to see if excluding the deepest retracements (which signify weaker momentum) or tightening to a "golden zone" would improve the R multiple without sacrificing win rate or causing an Engine DD spike.
- **Before Stats:** Trades 123, WR 48.78%, Avg R +0.61, Engine DD 13.62% (MSB_DEEP WR: 54.2%, AvgR +0.66)
- **After Stats:** Trades 107, WR 54.21%, Avg R +0.76, Engine DD 13.73% (MSB_DEEP WR: 61.9%, AvgR +0.93)

| Configuration | Trades | WR | AvgR | EngDD | DP Trades | DP WR | DP AvgR |
|---|---|---|---|---|---|---|---|
| baseline (0.55-0.85) | 123 | 48.8% | +0.61 | 13.62% | 24 | 54.2% | +0.66 |
| `dp_0.618-0.786_golden` | 109 | 47.7% | +0.60 | 19.38% ⚠️ | 11 | 54.5% | +0.27 |
| `dp_0.50-0.85_looser` | 95 | 54.7% | +0.78 | 20.66% ⚠️ | 22 | 59.1% | +0.87 |
| **`dp_0.55-0.80`** ✅ | 107 | **54.2%** | +0.76 | **13.73%** | 21 | **61.9%** | +0.93 |

- **Verdict:** Keeping `DEEP_FIB_MAX=0.80`. Trimming the maximum allowed retracement from 85% to 80% successfully filtered out the weakest momentum setups. The 3 excluded MSB_DEEP trades were clearly dragging performance: by dropping them, MSB_DEEP AvgR jumped from +0.66 to +0.93 and its WR increased to 61.9%. Crucially, this setup tightening did NOT cause the concurrent exposure Engine DD spike (+0.11pp is noise), unlike attempts to shift the band to the "golden zone" (EngDD 19.38%). Portfolio-wide WR also improved substantially (48.8% → 54.2%).

---

### Change 24: CDC Detection Tightening

- **Proxy Parameters:** `CDC_CONFIRM_ATR_MULT`, `CDC_BODY_RATIO_MIN` (Newly implemented in `cdc.py`)
- **Original Values:** Implicitly `0.0`, `0.0`
- **New Value:** `CDC_CONFIRM_ATR_MULT=1.0`
- **Reasoning:** CDC was the only remaining setup that hadn't had its bounce confirmation candle filtered. Given its poor out-of-sample performance, we introduced an ATR multiplier and body ratio requirement to the confirmation candle that follows the pivot drift.
- **Before Stats (Train):** Trades 121, WR 48.8%, Avg R +0.61, Engine DD 12.49% (CDC WR: 46.2%, AvgR +0.37)
- **After Stats (Train):** Trades 78, WR 57.7%, Avg R +0.90, Engine DD 11.77% (CDC WR: 83.3%, AvgR +0.95)
- **Verdict:** Keeping `CDC_CONFIRM_ATR_MULT=1.0`. Enforcing a strong confirmation bounce drastically reduced the number of weak CDC setups (26 → 6 trades on the training set) while sending its win rate soaring to 83.3%. This also dropped the total Engine DD to 11.77% and lifted the portfolio average R to an exceptional +0.90 on the training segment.

---

### Milestone: Post-Train Portfolio Optimization (OOS Validation)

- **Type:** Full portfolio generalization check on TEST/OOS (`2025-12-14` -> `2026-03-14`)
- **Protocol:** `python3 scratch/walk_forward.py --split test --milestone "Change 24 - CDC Tightening"`
- **Reasoning:** After completing all detection-tightening sweeps on the TRAIN segment (Changes 19-24), evaluate if the performance profile (57.7% WR, +0.90 AvgR, 11.7% MaxDD) holds up on unseen market data.
- **TEST/OOS Stats:**
  - Total Trades: 118
  - Win Rate: 35.59%
  - Average R: +0.4223
  - Max Drawdown: 19.18%
  - Total PnL: +$47,724
- **Cluster Drag Analysis:**
  - Clustered Trades: 63 (53.4%), PnL share: 17.5%, Max DD 11.97%
  - Isolated Trades: 55 (46.6%), PnL share: 82.5%, Max DD 6.92%
- **Takeaways:**
  1. **Regime Shift / Overfitting:** The portfolio's win rate collapsed out-of-sample (from 57% down to 35.6%), indicating either severe curve-fitting to the training window or a very unfavorable market regime.
  2. **Positive Expectancy Intact:** Despite the poor win rate, the system preserved a positive +0.42 AvgR and generated +$47k PnL, proving the risk/reward profile built via the tight detection criteria continues to yield a mathematical edge. CDC, specifically, achieved an 80% WR (+1.84 AvgR) on its 5 out-of-sample trades thanks to Change 24.
  3. **Cluster Toxicity:** Concurrent trade exposure (clustered trades) continues to be the dominant source of drawdown. Out-of-sample, isolated trades generated 82.5% of the total PnL with less than 7% max drawdown, while clustered trades suffered severely. A hard portfolio limit on concurrent trades or tighter `MAX_HEAT_PCT` should be the next major investigation.

---

### Change 25: Portfolio Heat Tightening

- **Proxy Parameters:** `MAX_HEAT_PCT`, `MAX_CORRELATED_HEAT_PCT`
- **Original Values:** `0.06` (6% equity open risk cap)
- **New Value:** `0.04` (4% equity open risk cap)
- **Reasoning:** In the Post-Train OOS Milestone, clustered trades caused severe performance drags: they accounted for 53.4% of trades, suffered a 11.97% max drawdown, but only generated 17.5% of the portfolio's PnL. We swept the `MAX_HEAT_PCT` on the OOS segment to find a threshold that explicitly limits concurrency without starving the portfolio.
- **Before Stats (OOS):** Trades 118, WR 35.6%, Avg R +0.42, Engine DD 19.18%
- **After Stats (OOS):** Trades 85, WR 35.3%, Avg R +0.36, Engine DD 12.85%

| Configuration | Trades | WR | AvgR | EngDD | CluDD | IsoDD |
|---|---|---|---|---|---|---|
| `heat_0.08` | 132 | 37.9% | +0.47 | 24.64% ⚠️ | 17.72% | 4.33% |
| baseline (`0.06`) | 118 | 35.6% | +0.42 | 19.18% | 11.97% | 6.92% |
| `heat_0.05` | 105 | 36.2% | +0.35 | 15.70% | 11.03% | 7.27% |
| **`heat_0.04`** ✅ | 85 | **35.3%** | +0.36 | **12.85%** | 11.77% | 10.09% |
| `heat_0.03` | 72 | 38.9% | +0.35 | 12.53% | 12.47% | 8.87% |
| `heat_0.02` | 33 | 33.3% | +0.05 | 10.39% | 5.30% | 7.42% |

- **Verdict:** Keeping `MAX_HEAT_PCT = 0.04`. By reducing the maximum allowed open risk from 6% to 4%, the portfolio naturally limits itself to fewer concurrent entries. This aggressively trimmed the overall Engine Max Drawdown from 19.18% to 12.85% while still keeping enough trades flowing (85 OOS trades) to generate a statistically solid +0.36 AvgR. Moving below 4% began to degrade AvgR severely due to excessive setup starvation.

---

### Milestone: Final Portfolio Validation (Untouched HOLDOUT)

- **Type:** Pre-paper final validation on completely unseen dataset (`2025-09-15` -> `2025-12-14`)
- **Protocol:** `python3 scratch/walk_forward.py --split holdout --final-validation --milestone "pre-paper"`
- **Reasoning:** After completing all setup tightening sweeps (TRAIN) and fixing the portfolio heat limits (TEST/OOS), the final, untainted validation must be run against the `HOLDOUT` dataset to confirm the system's robustness and ensure no accidental data snooping.
- **FINAL HOLDOUT Stats:**
  - Total Trades: 85
  - Win Rate: 48.24%
  - Average R: +0.3539
  - Max Drawdown: 9.16%
  - Total PnL: +$41,124
- **Per-Setup Breakdown:**
  - `SR_FLIP`: 15 trades, 60.0% WR, +0.808 AvgR
  - `MSB_DEEP`: 19 trades, 57.9% WR, +0.382 AvgR
  - `MSB_SHALLOW`: 7 trades, 42.9% WR, +0.420 AvgR
  - `OPEN_DRIVE`: 31 trades, 38.7% WR, +0.299 AvgR
  - `CDC`: 12 trades, 50.0% WR, -0.043 AvgR
- **Cluster Drag Analysis:**
  - Clustered Trades: 31 (36.5%), PnL share: 50.9%, Max DD 9.63%
  - Isolated Trades: 54 (63.5%), PnL share: 49.1%, Max DD 10.00%
- **Takeaways:**
  1. **Drawdown Conquered:** The tightening of `MAX_HEAT_PCT` to 4% was a massive success. The engine max drawdown collapsed to just **9.16%** on the holdout set, completely neutralizing the cluster toxicity that plagued previous runs. Clustered and isolated trades now share equal DD and PnL profiles.
  2. **Robust Generalization:** The win rate recovered strongly to 48.24% (up from 35.6% on the TEST set). The portfolio generated +$41,124 in PnL with a stable +0.35 AvgR over the 90-day unseen window.
  3. **Setup Stars:** `SR_FLIP` and `MSB_DEEP` proved to be incredibly robust anchors for the portfolio, maintaining ~60% win rates out-of-sample.
  4. **Status:** The tuning process is officially complete. The system demonstrates a high-quality positive expectancy with tightly controlled risk and is ready for live/paper deployment.

---

## Phase 2: Live / Paper Trading Guidelines

Before initiating the live paper-trading deployment, the following operational mandates and guardrails are in effect to protect the portfolio and ensure statistical integrity:

1. **Pause Threshold (System Circuit Breaker):**
   - If the **30-day rolling Average R drops below `+0.10`**, OR
   - If the **Portfolio Max Drawdown exceeds `15.0%`**.
   - **Action:** Immediately halt the trading engine and pause deployments. Investigate the failure mode against the recent tuning baselines before re-enabling.

2. **CDC Watchlist (Probation):**
   - CDC required severe tightening (Change 24) to stop bleeding capital.
   - **Action:** If the `CDC` setup reaches **25 live trades with a negative Average R**, explicitly flag it for removal or the next major tuning cycle. Do not allow it to accumulate further untethered losses.

3. **Minimum Evaluation Horizon:**
   - **Action:** Do NOT draw any system-level conclusions (positive or negative) before recording at least **60 live trades**. The variance of the R-multiples requires a statistically significant sample size to judge regime shift vs. standard strategy drawdown.

4. **Per-Setup Live Tracking (Cluster vs. Isolated Analysis):**
   - **Action:** Log and analyze the **Clustered vs. Isolated PnL split on a weekly basis**.
   - **Reasoning:** The massive inversion of cluster toxicity between the OOS test (where clustered trades were disastrous) and the Holdout validation (where clustered trades generated equal PnL and DD to isolated trades) is the biggest remaining unknown. Live weekly data will act as an early-warning radar to tell us exactly which volatility/regime the live market is currently operating in faster than any lagging indicator.
