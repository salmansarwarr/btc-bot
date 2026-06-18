# Consolidated Build Specification
## Automated Trading System — Gap Resolution & Resolved Parameter Set

**Source documents:** `1-trading_system_specification.md`, `2-proxy_rules_tradeoffs.md`, `3-technical_specification.md`
**Purpose:** Single authoritative reference for implementation. Supersedes any conflicting detail in the three source documents.

---

## Part I — Inconsistencies Between Spec (Doc 1) and Pseudocode (Doc 3)

### I-1: HTF Bias Lookback Window — Missing Neutral Threshold

**Doc 1 (§1.3):** "If structure is ambiguous (no factual MSB in either direction in the last N=20 HTF candles), Bias = NEUTRAL."

**Doc 3 (`update_htf_bias`):** `detect_factual_msb(asset, D1)` is called with no lookback argument. There is no `N=20` constraint enforced anywhere in the pseudocode — the function would return `None` only if no MSB exists at all in the entire pivot registry, not within the last 20 bars.

**Resolution:** `detect_factual_msb` must accept a `lookback_bars` parameter (default 20). If no factual MSB is found within that window, the function returns `None` and bias is set to `NEUTRAL`. If `last_msb` exists but was detected more than 20 bars ago, it still counts — the spec says "no factual MSB in the last N=20 candles," implying the most recent MSB must fall within the window. Add `N_HTF_BIAS_LOOKBACK: 20` to `CONFIG`.

---

### I-2: Bias Veto Uses 10-Bar EMA50 Lag — Not Defined in Either Source Doc

**Doc 3 (`update_htf_bias`):** `ema50_prior = Indicators[asset][D1].ema_50_at_lag(10)` — uses a 10-bar lag to determine slope direction.

**Doc 1 and Doc 2:** The EMA50 slope veto is introduced in Doc 2 (§2, Proxy B) as "50 EMA slope vs. 10 bars ago." This is the only reference and it is a **recommendation**, not a resolved parameter. The 10-bar slope window is implicit.

**Resolution:** Explicitly define `EMA50_SLOPE_LAG_BARS: 10` in `CONFIG`. This is the Doc 2 recommended value and is adopted as the default.

---

### I-3: Management Mode Assignment Is Inverted vs. Spec

**Doc 1 (§5.1):** "Use aggressive mode if conviction score ≤ 2; conservative mode if score = 3."

**Doc 3 (`evaluate_entry`):** `management_mode = AGGRESSIVE if conviction <= 2 else CONSERVATIVE`

This matches the spec correctly. However, Doc 3 (§3.4.4 `check_fta_interaction`) compound logic reads: "if `trade.management_mode == AGGRESSIVE` → `compound_position`" — but aggressive mode is associated with *lower* conviction, which is a conceptual inconsistency. In the spec, "aggressive" means close at FTA rejection; in the code it also means compound on FTA break. Both behaviors are attributed to the same mode.

**Resolution:** The code logic is internally consistent — aggressive mode closes faster AND compounds faster, which matches a high-activity, lower-conviction style. The spec's wording is slightly misleading but the code interpretation is the correct one. No code change needed; add a comment in `check_fta_interaction` clarifying: "Aggressive mode: both faster exits (FTA reject → close) and faster adds (FTA break → compound) — aggressive refers to trading frequency, not directional confidence."

---

### I-4: SR_FLIP Stop Calculation Contains Literal Range Notation

**Doc 3 (`compute_stop`):**
```python
offset = atr * (CONFIG.BREAK_CLOSE_BEYOND_ATR_MULT to 2x that)  # 0.1-0.2x ATR
```
This is pseudocode prose, not executable. `BREAK_CLOSE_BEYOND_ATR_MULT` = 0.15, so "2x that" = 0.30, but Doc 1 (§4.2) specifies "0.1–0.2× ATR." The `BREAK_CLOSE_BEYOND_ATR_MULT` parameter (0.15) was defined for clean-break detection, not stop placement, yet it is being reused here with a different intended range.

**Resolution:** Add a dedicated config parameter `SR_FLIP_STOP_ATR_MULT: 0.15` (midpoint of the 0.1–0.2 range from Doc 1). Replace the range notation with `offset = atr * CONFIG.SR_FLIP_STOP_ATR_MULT`. The `BREAK_CLOSE_BEYOND_ATR_MULT` parameter is not the right reference for stop placement.

---

### I-5: HTF Swing Expiry Uses Wrong Config Reference

**Doc 3 (`check_time_expiry`):**
```python
max_bars = CONFIG.EXPIRY_TRAP_BARS * CONFIG.EXPIRY_HTF_MULTIPLIER  # ~40 bars on idea TF
```
`EXPIRY_TRAP_BARS = 4`, `EXPIRY_HTF_MULTIPLIER = 10` → 40 bars. But Doc 1 (§6.3) specifies "~40–80 bars on the idea's own timeframe." Using `EXPIRY_TRAP_BARS` as the base is semantically wrong — HTF expiry has nothing to do with trap expiry. If `EXPIRY_TRAP_BARS` is ever tuned (a likely scenario), HTF expiry changes silently.

**Resolution:** Add `EXPIRY_HTF_BASE_BARS: 10` to `CONFIG`. Replace the calculation with `CONFIG.EXPIRY_HTF_BASE_BARS * CONFIG.EXPIRY_HTF_MULTIPLIER`. Default result (10 × 10 = 100 bars) is slightly higher than the 40–80 range; adjust `EXPIRY_HTF_MULTIPLIER` to 6 for an ~60-bar midpoint default, or keep 10 and document that the range is intentionally conservative.

**Adopted value:** `EXPIRY_HTF_BASE_BARS: 8`, `EXPIRY_HTF_MULTIPLIER: 8` → 64 bars (midpoint of 40–80 range). Both parameters independently configurable.

---

### I-6: `stall_band_counter` Is Not Initialized in `TradeState`

**Doc 3 (`check_stalling`):** `trade.stall_band_counter = trade.stall_band_counter + 1 if within_band else 0`

`stall_band_counter` does not appear in the `TradeState` definition. On first access this would raise `AttributeError`.

**Resolution:** Add `stall_band_counter: int = 0` to the `TradeState` struct. Also add `expiry_tightened: bool = False` (referenced in `check_time_expiry` but likewise absent from `TradeState`).

---

### I-7: `detect_pattern_failure` Is Absent from the Spec's Detection Logic

**Doc 1 (§5.5):** "This is functionally the CDC setup (2.4) viewed from the failure side — the system should treat CDC and Pattern Failure as the same detection logic with direction determined by which side resolves."

**Doc 3:** `detect_pattern_failure` is listed in the `run_setup_detection` call under "Range-context setups," but it's described in the stub comment as a separate function. `detect_cdc` returns a `CDC`-typed candidate; `detect_pattern_failure` is a separate call with no shared implementation shown.

**Resolution:** Per Doc 1's explicit instruction, `detect_pattern_failure` must be the same function as `detect_cdc`, called with a `pattern_failure_mode=True` flag that inverts the returned direction and setup type. The state machine (`BREAK_1_DONE → reverse clean break`) is identical; only the label and direction differ. Remove the duplicate call in `run_setup_detection` and replace with: `candidates += detect_cdc(asset, timeframe, include_pattern_failure=True)`.

---

### I-8: Relative Strength Filter (§2.11) Has No Implementation

**Doc 1 (§2.11):** "On a broad-market red day, only long assets that are green or down less than the BTC/market mean." This is listed as an always-active filter for trending-market setups.

**Doc 3:** No function `check_relative_strength_filter` exists. The `MarketBasket` data structure is defined in §1.3, and `btc_eth_avg_24h_change` / `top20_avg_24h_change` are declared as inputs, but they are never consumed in any detection or entry logic.

**Resolution:** Add a `passes_relative_strength_filter(candidate, asset)` check inside `evaluate_entry`, applied only when `trend_classification == LOCKOUT_TREND` and `candidate.direction == UP`:
```python
if ctx.trend_classification == LOCKOUT_TREND and candidate.direction == UP:
    if MarketBasket.btc_eth_avg_24h_change < 0:
        asset_24h = get_24h_change(asset)
        if asset_24h <= MarketBasket.btc_eth_avg_24h_change:
            log_skipped_setup(candidate, reason="RELATIVE_STRENGTH_FILTER")
            return
```
On a green market day (`btc_eth_avg_24h_change >= 0`), the filter does not apply.

---

### I-9: `compute_liquidation_zscore` Uses a Different Method Than Configured

**Doc 3 (`check_capitulation`):** `compute_liquidation_zscore(asset) >= CONFIG.LIQ_SIGMA_THRESHOLD` — implies a z-score / standard-deviation approach (Proxy A from Doc 2, item 11).

**CONFIG:** `LIQ_SIGMA_THRESHOLD: 2.0` — confirms Proxy A.

This is consistent. But Doc 1 (§2.11, Liquidation Flush setup detection) uses the same threshold as the *per-asset* setup trigger, while `check_capitulation` applies it *market-wide*. The same function name and threshold being reused for two distinct purposes (single-asset setup trigger vs. market-wide capitulation) is an ambiguity risk.

**Resolution:** Rename the per-asset version to `compute_asset_liquidation_zscore(asset)` and the portfolio-level one remains as-is. The threshold `LIQ_SIGMA_THRESHOLD: 2.0` applies to both. Document the distinction in code comments.

---

### I-10: Drawdown Recovery Condition Inconsistently Specified

**Doc 1 (§8.4):** "Reduce per-trade risk... until equity recovers to within -5% of the prior high." The recovery threshold is -5% from ATH.

**Doc 3 (`check_drawdown_tier`):** `if equity >= ath * (1 - 0.05): drawdown_tier = 0` — only resets to tier 0, with no graduated step-down from tier 2 back to tier 1 before reaching tier 0.

**Resolution:** Add intermediate recovery logic: tier 2 steps back to tier 1 when `equity >= ath * (1 - CONFIG.DRAWDOWN_TIER_2_PCT * 0.5)` (i.e., halfway back from the tier-2 threshold). Full reset to tier 0 only at `equity >= ath * 0.95` as currently coded. Add `DRAWDOWN_RECOVERY_HYSTERESIS: 0.5` to `CONFIG` to parameterize the midpoint.

---

## Part II — Proxy Rules from Doc 2 Not Reflected in the Pseudocode

### II-1: Pivot Major — Composite A+C Filter (Doc 2, §3 recommendation)

**Doc 2 recommendation:** "Use A for setup detection (cheap, real-time) and C as a post-hoc filter for which detected pivots get logged as 'major' vs. 'minor' for the conviction score."

**Doc 3:** `update_pivot_registry` runs only the N-candle fractal check (Proxy A). There is no C-layer (percentile-of-range) applied when assigning `strength = MAJOR`. `PIVOT_MAJOR_PERCENTILE: 0.10` appears in CONFIG but is never used.

**Resolution:** After fractal detection, apply the percentile filter when computing `conviction_score` — not at detection time (to preserve detection frequency). In `compute_conviction_score`, when checking `candidate.trigger_pivot.strength == MAJOR`, additionally verify the pivot sits in the top/bottom 10% of price range over the trailing 50 bars. If it fails the percentile check, treat it as MINOR for scoring purposes only (it still triggers setup detection). Add: `PIVOT_PERCENTILE_SCORING_ENABLED: true`, `PIVOT_PERCENTILE_LOOKBACK: 50`.

---

### II-2: Minor Pivot — "Previously Respected" Confidence Multiplier (Doc 2, §4 recommendation)

**Doc 2 recommendation:** "Layer B as a confidence multiplier when available (a minor level that's also been previously respected gets a higher conviction-score contribution than one that's purely fractal-based)."

**Doc 3:** No logic tracks first-contact price reactions per level. Minor pivots in the conviction score always contribute 0 (only MAJOR contributes 1 point).

**Resolution:** This is a data-state addition. Add a `first_reaction_confirmed: bool = False` field to `PivotFlag`. When a minor pivot is approached and price reverses by at least `0.25 × ATR(14)` on first contact, set `first_reaction_confirmed = True`. In `compute_conviction_score`, if the trigger pivot is MINOR but `first_reaction_confirmed == True`, contribute 0.5 to the score (round to nearest integer at the final threshold comparison, so a score of 1.5 rounds to 2 and clears the direct-entry threshold). Add `MINOR_PIVOT_RESPECTED_BONUS: 0.5` to `CONFIG`.

---

### II-3: "Clean Break" — Composite A+C, Not A Alone (Doc 2, §5 recommendation)

**Doc 2 recommendation:** "Composite of A + C (magnitude AND close-strength) as the default clean break test."

**Doc 3 (`is_clean_break`):** Implements A (body ATR, close-beyond ATR) and C (wick ratio — `BREAK_WICK_RATIO_MAX: 0.25`). This is **already implemented correctly** — Doc 3 includes the wick ratio check that corresponds to Proxy C. **No gap.**

---

### II-4: CDC No-Interaction — Log A and B for Backtest Analysis (Doc 2, §6 recommendation)

**Doc 2 recommendation:** "Log setups under both A and B classifications in the journal so you can later assess how much quality/frequency you're trading off."

**Doc 3:** Only Proxy A is applied operationally. No dual-classification logging exists in `TradeJournalEntry` or `SkippedSetupLogEntry`.

**Resolution:** Add `cdc_qualifies_zero_tolerance: bool | None` to `TradeJournalEntry` (populated for CDC and Pattern Failure setups). This records whether the setup would also have qualified under Proxy B (literal zero-touch), enabling the post-hoc frequency/quality analysis Doc 2 recommends. Compute at entry-log time: `cdc_qualifies_zero_tolerance = not any_wick_touched_level_exactly(...)`. No operational change.

---

### II-5: Shallow Pullback — ATR Sanity-Check Override (Doc 2, §7 recommendation)

**Doc 2 recommendation:** "A as primary (Fib), with B as a sanity-check override — if a 0.236–0.382 Fib retracement also exceeds 3×ATR(14), treat it as NOT shallow regardless of the Fib reading."

**Doc 3 (`detect_shallow_pullback`):** `SHALLOW_ATR_CAP_MULT: 3.0` is defined in CONFIG but the function itself is only stubbed. The ATR override must be part of the shallow pullback detector implementation.

**Resolution:** In the `detect_shallow_pullback` implementation, after checking `SHALLOW_FIB_MIN <= retracement_ratio <= SHALLOW_FIB_MAX`, additionally reject if `retracement_absolute > CONFIG.SHALLOW_ATR_CAP_MULT * atr`. This check is already parameterized; it must be wired into the detector.

---

### II-6: Deep Pullback — Tolerance Band + B as Confluence Bonus (Doc 2, §8 recommendation)

**Doc 2 recommendation:** "A with a tolerance band (0.55–0.85) to avoid near-miss exclusions, and use B as a confluence bonus (higher conviction score) when both align."

**Doc 3:** `DEEP_FIB_MIN: 0.55`, `DEEP_FIB_MAX: 0.85` — the tolerance band is already adopted in CONFIG. The B-layer confluence bonus (pullback re-enters prior consolidation range) is not implemented.

**Resolution:** Add `deep_pullback_consolidation_confluence: bool` to `SetupCandidate` for MSB Setup B detections. If the pullback also re-enters the prior consolidation range (requires `active_impulse_leg` to have an associated pre-impulse range), set this field to `True`. In `compute_conviction_score`, add +0.5 to score when this field is `True` (same rounding logic as the minor-pivot bonus). Add `DEEP_PULLBACK_CONFLUENCE_BONUS: 0.5` to `CONFIG`.

---

### II-7: Stalling — Re-Entry Band as Secondary Early-Warning for Traps (Doc 2, §10 recommendation)

**Doc 2 recommendation:** "Add C as a secondary early-warning flag specifically for trap setups (SFP/CDC/Pattern Failure), since re-entry into the trigger zone is a stronger and more specific failure signal for those setups."

**Doc 3 (`check_stalling`):** Only Proxy A (ATR-band around the trigger level, consecutive bars). The re-entry pattern (price moves away then returns to trigger zone within a timing window) is not tracked.

**Resolution:** In `check_stalling`, add a branch for TRAP-class trades:
```python
if trade.setup_class == TRAP:
    distance_moved = abs(current_price - trade.entry_price)
    if distance_moved > CONFIG.STALL_ATR_MULT * atr:  # price moved away
        trade.trap_moved_away = True
    if trade.trap_moved_away and abs(current_price - trade.pivot_used.price) <= CONFIG.STALL_ATR_MULT * 2 * atr:
        # returned to trigger zone after moving away
        reduce_position(trade, fraction=0.5)
        trade.stalling_flag = True
        log_event(trade, STALLING_FLAG, {"reason": "re-entry_into_trigger_zone"})
```
Add `trap_moved_away: bool = False` to `TradeState`. Add `TRAP_REENTRY_ATR_MULT: 2.0` (band around trigger level for re-entry detection) to `CONFIG`.

---

### II-8: Liquidation Spike — Proxy C Preferred Over A When OI Available (Doc 2, §11 recommendation)

**Doc 2 recommendation:** "C is conceptually best if you have reliable OI data for your asset set; fall back to B where OI data is unreliable but history is long enough; use A only as last resort."

**Doc 3:** Uses Proxy A (z-score) for all assets universally. `CONFIG.LIQ_SIGMA_THRESHOLD: 2.0` is an A-type threshold. There is no fallback hierarchy.

**Resolution:** Add a `liquidation_proxy_method: enum {ZSCORE, PERCENTILE, OI_PCT}` field to the per-asset config (not global CONFIG, since it varies by data quality). At runtime, `compute_asset_liquidation_zscore` routes to the appropriate method:
- If `oi_hourly` feed available and history ≥ 30 days: use Proxy C (`liquidation_notional / oi_at_window_start > THRESHOLD`)
- Else if liquidation history ≥ 90 days: use Proxy B (90-day percentile, top 5%)
- Else: fall back to Proxy A (z-score, 20-day)

Add to CONFIG: `LIQ_OI_PCT_THRESHOLD: 0.02` (Proxy C), `LIQ_PERCENTILE_THRESHOLD: 0.95` (Proxy B). `LIQ_SIGMA_THRESHOLD: 2.0` remains as the Proxy A fallback.

---

### II-9: Mega Wipe — A + B Dual Gate (Doc 2, §12 recommendation)

**Doc 2 recommendation:** "A as primary trigger, with B as secondary confirmation gate — require both A's OI/liquidation condition AND a minimum price drawdown."

**Doc 3 (`check_capitulation`):** Already implements the dual gate:
```python
if (oi_decline_7d >= CONFIG.OI_DECLINE_PCT_7D and liq_spike and price_drawdown >= CONFIG.MEGA_WIPE_PRICE_DRAWDOWN)
```
`MEGA_WIPE_PRICE_DRAWDOWN: 0.20` is set. **No gap — already implemented.**

---

### II-10: Portfolio ATH — Backstop Trigger (Doc 2, §13 recommendation)

**Doc 2 recommendation:** "A as primary (best matches 'significant' = fast/large), with B as a backstop — if A hasn't triggered in 90+ days despite the portfolio being at/near ATH, force a smaller (5%) realization."

**Doc 3 (`check_ath_realization`):** The backstop is implemented:
```python
elif days_since(PortfolioState.last_realization_date) >= CONFIG.ATH_BACKSTOP_DAYS:
    realize_to_cash(CONFIG.ATH_BACKSTOP_PCT * equity)
```
`ATH_BACKSTOP_DAYS: 90`, `ATH_BACKSTOP_PCT: 0.05`. **No gap — already implemented.** However, the backstop fires on any ATH, not specifically when "at/near ATH." The condition should only fire if `equity >= equity_ath * 0.99` (within 1% of ATH). Add a proximity guard.

---

### II-11: Portfolio Heat — A as Hard Ceiling + C as Soft Cooloff (Doc 2, §14 recommendation)

**Doc 2 recommendation:** "A as the hard ceiling (never exceed 6%/8%), with C layered on top as a soft reduction during losing streaks."

**Doc 3:** Both are implemented — `enforce_portfolio_heat` enforces hard caps; `update_heat_cooloff` computes `effective_max_heat` using `HEAT_COOLOFF_REDUCTION`. However, `enforce_portfolio_heat` still references `CONFIG.MAX_HEAT_PCT` directly, not `PortfolioState.effective_max_heat`. This means the soft cooloff is computed but never actually used.

**Resolution:** Replace `CONFIG.MAX_HEAT_PCT` in `enforce_portfolio_heat` with `PortfolioState.effective_max_heat` (which equals `CONFIG.MAX_HEAT_PCT` normally and a reduced value during a loss streak). The hard ceiling is preserved since `effective_max_heat` is always ≤ `CONFIG.MAX_HEAT_PCT`.

---

### II-12: Partial Exit — FTA-Break Override (Doc 2, §15 recommendation)

**Doc 2 recommendation:** "If price reaches an FTA and the 'FTA breaks cleanly → compound' condition fires before the scheduled partial would be taken, skip that partial and roll its allocation into the compounding add."

**Doc 3 (`check_fta_interaction`):** The `continue` statement after `FTA_BREAK_COMPOUND` correctly skips `take_scheduled_partial`. The comment reads "FTA cleanly broken → SKIP scheduled partial for this FTA." **Already implemented correctly.** No gap.

---

### II-13: Drawdown Tiers — C as Early-Warning Layer (Doc 2, §16 recommendation)

**Doc 2 recommendation:** "C as a secondary early-warning layer that can trigger Tier 1 even before equity drawdown reaches -10%, if a losing streak suggests something may be off."

**Doc 3 (`check_drawdown_tier`):**
```python
if PortfolioState.consecutive_losses >= CONFIG.HEAT_COOLOFF_LOSS_STREAK:
    PortfolioState.drawdown_tier = max(PortfolioState.drawdown_tier, 1)
```
**Already implemented.** `HEAT_COOLOFF_LOSS_STREAK: 3` serves as the early-warning threshold. No gap.

---

### II-14: Conviction Score — Proxy A (Equal Weights) Confirmed; B/C Not Needed

**Doc 2 (Additional item A):** Proposes weighted scoring (B) or continuous logistic scoring (C) as alternatives to the equal-weight default.

**Resolution:** Retain Proxy A (equal weights) as specified. Doc 2's own reasoning — "the weights themselves are now additional discretionary parameters requiring justification" and "significantly harder to explain in the journal review process" — supports keeping A for the initial deployment. Document that weights can be revisited after ≥100 trade journal entries comparing proxy-flagged setups to discretionary judgment.

---

### II-15: RSI Divergence — Extreme Zone Filter Not Implemented (Doc 2, Additional item B)

**Doc 2 (Additional item B, Proxy B):** "Require the RSI pivot to also fall within an extreme zone (< 30 for bullish divergence, > 70 for bearish)."

**Doc 3 (`detect_momentum_divergence`):** Stubbed. No extreme-zone filter is parameterized.

**Resolution:** When implementing `detect_momentum_divergence`, add a configurable extreme-zone gate defaulting to **enabled** (Doc 2's own recommendation, since mid-range divergences are statistically weak). Add `RSI_DIV_EXTREME_LOW: 35` and `RSI_DIV_EXTREME_HIGH: 65` to CONFIG (slightly relaxed from the ±30/70 hard levels to avoid over-filtering in mildly extended conditions).

---

### II-16: Relative Strength Basket — Proxy A (BTC+ETH) Confirmed

**Doc 2 (Additional item C):** BTC+ETH average (Proxy A) vs. top-20 basket (Proxy B).

**Resolution:** Retain Proxy A. The top-20 basket adds data maintenance burden and is prone to composition drift. BTC+ETH sufficiently captures broad-market direction for the filter's purpose. `MarketBasket.btc_eth_avg_24h_change` is the operative field. `top20_avg_24h_change` remains in the data structure as an optional field for future comparison, but is not used in any logic.

---

## Part III — Undefined Variables, Thresholds, and Parameters

The following items are referenced in the pseudocode but have no definition in any source document.

### III-1: `MAX_PENDING_AGE` — FTA Confirmation Timeout

**Doc 3 (`check_pending_fta_confirmations`):** `elif now() - pending.created > MAX_PENDING_AGE:` — `MAX_PENDING_AGE` is not in `CONFIG` and is not discussed in Doc 1 or Doc 2.

**Resolved value:** `MAX_PENDING_AGE_BARS: 20` on the idea timeframe (not wall-clock time, to be timeframe-consistent). A setup pending FTA confirmation for more than 20 bars of its idea timeframe has likely seen its context shift. Add to CONFIG: `MAX_PENDING_AGE_BARS: 20`.

**Rationale:** 20 bars corresponds to roughly one trading week on H1, one month on D1. At these intervals, the HTF bias and setup context would likely have been re-evaluated anyway.

---

### III-2: `correlation_bucket(asset)` — Not Defined

**Doc 3 (`enforce_portfolio_heat`):** `bucket = correlation_bucket(asset)` — the function is called but never defined. There is no specification of which assets belong to which correlation buckets.

**Resolved definition:** Correlation buckets are defined statically at bot configuration time as a mapping from asset name to bucket label. Default mapping:
- `BTC`, `ETH`, `BNB`, `SOL` → bucket `"BTC_CORE"`
- `LINK`, `UNI`, `AAVE`, `CRV` → bucket `"DEFI"`
- All others → bucket `"OTHER"` (each gets its own bucket by default, meaning the `MAX_CORRELATED_HEAT_PCT` cap applies only when multiple assets share an explicit bucket)

Add to CONFIG: `CORRELATION_BUCKETS: dict[str, str]` (asset → bucket name). The 8% correlated cap (`MAX_CORRELATED_HEAT_PCT`) applies per bucket. Assets without an assigned bucket are their own bucket.

---

### III-3: `deploy_capitulation_reserve_tranche` — Behavior Undefined

**Doc 3 (`check_capitulation`):** `deploy_capitulation_reserve_tranche(asset)` — the function is called but never defined. Doc 1 (§8.3) specifies the tranche logic: "25% of reserve per additional -10% market move from the point capitulation was detected."

**Resolved definition:**
```python
function deploy_capitulation_reserve_tranche(asset):
    reserve = PortfolioState.fund_balances["capitulation_reserve"]  # built via check_ath_realization
    price_drop_from_detection = compute_price_drop_since(asset, PortfolioState.capitulation_detected_date)
    tranches_earned = floor(price_drop_from_detection / 0.10)  # one tranche per -10%
    tranches_already_deployed = PortfolioState.capitulation_tranches_deployed.get(asset, 0)
    new_tranches = tranches_earned - tranches_already_deployed
    if new_tranches > 0:
        deploy_amount = reserve * 0.25 * new_tranches
        buy_core_fund(asset, deploy_amount)
        PortfolioState.capitulation_tranches_deployed[asset] = tranches_earned
```
Add `capitulation_tranches_deployed: dict[str, int]` to `PortfolioState`. Add `CAPITULATION_TRANCHE_DROP_PCT: 0.10` and `CAPITULATION_TRANCHE_SIZE: 0.25` to CONFIG. Note: the "capitulation reserve" is the cash pool built by `check_ath_realization` — this must be tracked as a sub-account in `fund_balances`.

---

### III-4: `lock_in_1R_stop` — Return Value Undefined

**Doc 3 (`check_dynamic_r`):** `new_stop = lock_in_1R_stop(trade, current_price(asset))` — the function is called but not defined.

**Resolved definition:**
```python
function lock_in_1R_stop(trade, current_price):
    initial_risk = abs(trade.entry_price - trade.stop_price)
    if trade.direction == UP:
        return current_price - initial_risk  # stop placed 1R below current
    else:
        return current_price + initial_risk  # stop placed 1R above current
```
This ensures the remaining position is protected at a minimum of 1R from current price. If the computed stop is less favorable than the existing stop (e.g., current price is very close to entry), the function should return `max(computed_stop, trade.stop_price)` for longs / `min(computed_stop, trade.stop_price)` for shorts — i.e., stops only move in the favorable direction.

---

### III-5: `approaching_target(trade)` — No Definition

**Doc 3 (`check_time_expiry`, HTF_SWING branch):** `if bars >= max_bars and not approaching_target(trade):`

**Resolved definition:** A trade is "approaching target" if `compute_progress_to_target(trade, current_price) >= 0.6` (60% of the way to the final target). Add `APPROACHING_TARGET_THRESHOLD: 0.6` to CONFIG.

---

### III-6: `ema_50_at_lag(10)` — Method Not in Data Model

**Doc 3 (`update_htf_bias`):** `ema50_prior = Indicators[asset][D1].ema_50_at_lag(10)` — a `_at_lag()` accessor is implied but not part of the `Indicators` struct.

**Resolution:** `Indicators[asset][timeframe]` stores only the current-bar value. To support lag access, either: (a) maintain an EMA50 mini-buffer (rolling 15-value deque alongside each indicator), or (b) compute the lagged value from the OHLCV buffer directly (`ema(buffer[asset][D1][-10:], period=50)[-1]`). Option (a) is cheaper at read time. Add `ema_50_buffer: deque(maxlen=15)` to the `Indicators` struct, updated on each D1 close.

---

### III-7: `signed_pnl(direction, entry_price, exit_price)` — Implicit Function

**Doc 3 (`compute_realized_r`):** `signed_pnl(trade.direction, trade.entry_price, partial.price)` — used without definition.

**Resolved definition:**
```python
function signed_pnl(direction, entry_price, exit_price):
    if direction == UP:
        return exit_price - entry_price
    else:
        return entry_price - exit_price
```
Per-unit (not absolute); caller multiplies by fraction/size.

---

### III-8: `compute_oi_decline_pct`, `compute_price_drawdown_pct` — Undefined

**Doc 3 (`check_capitulation`):** Both functions used but undefined.

**Resolved definitions:**
```python
function compute_oi_decline_pct(asset, days):
    oi_now = ExternalFeeds[asset].oi_hourly[-1]
    oi_prior = ExternalFeeds[asset].oi_hourly[-(days * 24)]
    return (oi_prior - oi_now) / oi_prior if oi_prior > 0 else 0

function compute_price_drawdown_pct(asset):
    recent_high = max(OHLCV_Bar.high for bar in buffer[asset][D1][-30:])
    current = buffer[asset][D1][-1].close
    return (recent_high - current) / recent_high if recent_high > 0 else 0
```
The 30-bar lookback for `recent_high` is implicit in the context (capitulation events are near-term phenomena). Add `CAPITULATION_DRAWDOWN_LOOKBACK_BARS: 30` to CONFIG.

---

### III-9: `N` in Neutral Bias MSB Ambiguity — Confirmed Value

**Doc 1 (§1.3):** "no factual MSB in either direction in the last N=20 HTF candles" — this N is explicit in Doc 1 but absent from CONFIG.

**Resolution:** Already addressed in I-1 above. `N_HTF_BIAS_LOOKBACK: 20` in CONFIG.

---

### III-10: Consolidation Detection Parameters — Partially Undefined

**Doc 1 (§2.11):** "at least 5 consecutive bars where each bar's range is < 0.7× ATR(14), and the consolidation range's total height is < 1.5× ATR(14)."

**Doc 3 CONFIG:** No parameters for these thresholds. `detect_consolidation_entry` is stubbed.

**Resolved values:** Add to CONFIG:
```
CONSOLIDATION_MIN_BARS: 5
CONSOLIDATION_BAR_RANGE_ATR_MULT: 0.7    # each bar's range must be below this
CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT: 1.5  # total range of consolidation zone
```
These map directly to Doc 1's specified values.

---

## Part IV — Resolved Full CONFIG (Canonical Reference)

This is the definitive CONFIG block incorporating all additions and corrections above. New entries are marked `# NEW`.

```python
CONFIG = {
    # ── Trend classification ──────────────────────────────────────────────────
    "ADX_TREND_THRESHOLD": 30,
    "ER_TREND_THRESHOLD": 0.6,
    "TREND_CONFIRM_BARS": 10,

    # ── HTF Bias ──────────────────────────────────────────────────────────────
    "N_HTF_BIAS_LOOKBACK": 20,                  # NEW (I-1, III-9)
    "EMA50_SLOPE_LAG_BARS": 10,                 # NEW (I-2)

    # ── Pivot definitions ─────────────────────────────────────────────────────
    "PIVOT_MAJOR_N": {"default": 2, "D1": 1, "W1": 1},
    "PIVOT_MINOR_N": 1,
    "PIVOT_MAJOR_ATR_MULT": 0.25,
    "PIVOT_MAJOR_PERCENTILE": 0.10,
    "PIVOT_PERCENTILE_SCORING_ENABLED": True,   # NEW (II-1)
    "PIVOT_PERCENTILE_LOOKBACK": 50,            # NEW (II-1)
    "MINOR_PIVOT_RESPECTED_BONUS": 0.5,         # NEW (II-2)

    # ── Clean break ───────────────────────────────────────────────────────────
    "BREAK_BODY_ATR_MULT": 1.0,
    "BREAK_CLOSE_BEYOND_ATR_MULT": 0.15,
    "BREAK_WICK_RATIO_MAX": 0.25,

    # ── Stop placement ────────────────────────────────────────────────────────
    "SR_FLIP_STOP_ATR_MULT": 0.15,              # NEW (I-4)
    "MIN_STOP_ATR_MULT": 0.5,

    # ── CDC no-interaction ────────────────────────────────────────────────────
    "CDC_NO_INTERACTION_ATR_MULT": 0.05,

    # ── Pullback depth ────────────────────────────────────────────────────────
    "SHALLOW_FIB_MIN": 0.236,
    "SHALLOW_FIB_MAX": 0.382,
    "SHALLOW_ATR_CAP_MULT": 3.0,
    "DEEP_FIB_MIN": 0.55,
    "DEEP_FIB_MAX": 0.85,
    "DEEP_PULLBACK_CONFLUENCE_BONUS": 0.5,      # NEW (II-6)

    # ── Candle Open Drive ─────────────────────────────────────────────────────
    "DRIVE_ATR_MULT": 1.0,
    "DRIVE_BODY_RANGE_RATIO_MIN": 0.6,

    # ── Stalling / time expiry ────────────────────────────────────────────────
    "STALL_ATR_MULT": 0.1,
    "STALL_BARS": 3,
    "TRAP_REENTRY_ATR_MULT": 2.0,               # NEW (II-7)
    "EXPIRY_TRAP_BARS": 4,
    "EXPIRY_TRAP_ATR_MULT": 1.0,
    "EXPIRY_CONTINUATION_BARS": 8,
    "EXPIRY_CONTINUATION_ATR_MULT": 0.5,
    "EXPIRY_CONTINUATION_TIGHTEN_ATR_MULT": 0.1,
    "EXPIRY_HTF_BASE_BARS": 8,                  # NEW (I-5, replaces reuse of EXPIRY_TRAP_BARS)
    "EXPIRY_HTF_MULTIPLIER": 8,                 # CHANGED from 10 → 8 (I-5, targets ~64-bar midpoint)

    # ── Momentum divergence ───────────────────────────────────────────────────
    "RSI_DIV_EXTREME_LOW": 35,                  # NEW (II-15)
    "RSI_DIV_EXTREME_HIGH": 65,                 # NEW (II-15)

    # ── Consolidation detection ───────────────────────────────────────────────
    "CONSOLIDATION_MIN_BARS": 5,                # NEW (III-10)
    "CONSOLIDATION_BAR_RANGE_ATR_MULT": 0.7,    # NEW (III-10)
    "CONSOLIDATION_TOTAL_HEIGHT_ATR_MULT": 1.5, # NEW (III-10)

    # ── Liquidation / OI thresholds ───────────────────────────────────────────
    "LIQ_SIGMA_THRESHOLD": 2.0,                 # Proxy A fallback
    "LIQ_PERCENTILE_THRESHOLD": 0.95,           # NEW (II-8) Proxy B
    "LIQ_OI_PCT_THRESHOLD": 0.02,               # NEW (II-8) Proxy C
    "OI_DECLINE_PCT_7D": 0.25,
    "MEGA_WIPE_PRICE_DRAWDOWN": 0.20,
    "CAPITULATION_TRANCHE_DROP_PCT": 0.10,      # NEW (III-3)
    "CAPITULATION_TRANCHE_SIZE": 0.25,          # NEW (III-3)
    "CAPITULATION_DRAWDOWN_LOOKBACK_BARS": 30,  # NEW (III-8)

    # ── Portfolio ATH realization ─────────────────────────────────────────────
    "ATH_GAIN_PCT_30D": 0.30,
    "ATH_REALIZATION_PCT": 0.10,
    "ATH_BACKSTOP_DAYS": 90,
    "ATH_BACKSTOP_PCT": 0.05,
    "ATH_BACKSTOP_PROXIMITY_PCT": 0.01,         # NEW (II-10) must be within 1% of ATH

    # ── Portfolio heat ────────────────────────────────────────────────────────
    "MAX_HEAT_PCT": 0.06,
    "MAX_CORRELATED_HEAT_PCT": 0.08,
    "HEAT_COOLOFF_LOSS_STREAK": 3,
    "HEAT_COOLOFF_REDUCTION": 0.25,
    "CORRELATION_BUCKETS": {},                  # NEW (III-2) set at bot config time

    # ── Risk per trade ────────────────────────────────────────────────────────
    "RISK_PCT_BY_CONVICTION": {3: 0.03, 2: 0.02, 1: 0.01, 0: 0.0},

    # ── Partial exit schedule ─────────────────────────────────────────────────
    "PARTIAL_SCHEDULE": [0.33, 0.33, 0.34],

    # ── Drawdown tiers ────────────────────────────────────────────────────────
    "DRAWDOWN_TIER_1_PCT": 0.10,
    "DRAWDOWN_TIER_2_PCT": 0.20,
    "DRAWDOWN_TIER_3_PCT": 0.30,
    "DRAWDOWN_TIER_1_RISK_MULT": 0.5,
    "DRAWDOWN_RECOVERY_HYSTERESIS": 0.5,        # NEW (I-10)

    # ── Conviction scoring ────────────────────────────────────────────────────
    "CONVICTION_DIRECT_ENTRY_THRESHOLD": 2,

    # ── FTA confirmation ──────────────────────────────────────────────────────
    "MAX_PENDING_AGE_BARS": 20,                 # NEW (III-1)

    # ── Target proximity ─────────────────────────────────────────────────────
    "APPROACHING_TARGET_THRESHOLD": 0.6,        # NEW (III-5)

    # ── Relative strength filter ──────────────────────────────────────────────
    # Uses MarketBasket.btc_eth_avg_24h_change; no threshold needed (outperform = any)
}
```

---

## Part V — Proxy Selection Decisions (One Choice Per Doc 2 Item)

For each item where Doc 2 presented alternatives, the following is the chosen proxy and the reasoning.

| # | Item | Chosen Proxy | Reasoning |
|---|------|-------------|-----------|
| 1 | Lockout Trend | **A+B combined** (ADX gate + ER trigger, asymmetric exit) | Matches Doc 2 recommendation. Conservative entry into trend mode prevents the largest misclassification cost (treating chop as trend). |
| 2 | HTF Directional Bias | **A primary + B veto** (MSB + EMA50 slope filter) | MSB-first preserves the system's invalidation logic coherence; EMA50 veto catches the most dangerous MSB-lag scenario (trend has already reversed at the MA level). |
| 3 | Major Pivot (detection) | **A** (N-fractal); **C** (percentile) for conviction scoring only | Cheap real-time detection + quality filter at scoring time, exactly as Doc 2 recommends. |
| 4 | Minor Pivot | **A** (N=1 fractal) + **B** (previously respected) as bonus | A generates the candidates; B upgrades conviction when a level has been market-tested. |
| 5 | Clean Break | **A+C composite** (ATR magnitude + wick ratio) | Already implemented in Doc 3. Volume (B) excluded due to crypto wash-trading quality concerns cited in Doc 2. |
| 6 | CDC No-Interaction | **A** (ATR buffer), dual-log B for journal analysis | A for live trading; B logged passively per Doc 2 recommendation to accumulate backtest evidence before tightening. |
| 7 | Shallow Pullback | **A** (Fib) + **B** as override sanity check | Preserves Fib-confluence logic; ATR cap prevents false positives on volatility-expanded assets. |
| 8 | Deep Pullback | **A** (tolerance band 0.55–0.85) + **B** as confluence bonus | Near-miss exclusions eliminated by band; consolidation confluence elevates conviction rather than gating. |
| 9 | Open Drive trigger | **A** (ATR + body/range) | Computationally cheapest; sub-TF data (B) reserved for assets where this is a primary strategy. |
| 10 | Stalling/Lingering | **A** (ATR band, N bars) + **C** (re-entry) for traps | C added for TRAP class because trigger-zone re-entry is a stronger failure signal for SFP/CDC/Pattern Failure specifically. |
| 11 | Liquidation Spike | **C preferred → B fallback → A last resort** per data quality | Hierarchical selection at per-asset config time; OI-based (C) is the most mechanistically accurate when data is clean. |
| 12 | Mega Wipe | **A + B dual gate** | Already implemented in Doc 3; both OI/liquidation mechanics and price drawdown confirmation required. |
| 13 | Portfolio ATH | **A primary + B backstop** | Already implemented; added ATH-proximity guard for backstop (II-10). |
| 14 | Portfolio Heat | **A hard ceiling + C soft cooloff** | Already implemented; fixed the effective_max_heat wiring bug (II-11). |
| 15 | Partial Exit | **A** (33/33/34 at FTAs) with FTA-break override | Already implemented with override; preserves system's compounding logic. |
| 16 | Drawdown Tiers | **A primary + C early-warning** | Already implemented; A is most auditable; C streak-trigger gives an early signal before equity damage accumulates. |
| A | Conviction Score | **A** (equal-weight 3-point) | Avoids relocating discretion into weight calibration; revisit after 100+ journal entries. |
| B | RSI Divergence Pivots | **A + extreme zone filter** (Proxy B applied to oscillator) | Mid-range divergences are weak; extreme-zone gate substantially improves signal quality. |
| C | Market Basket | **A** (BTC+ETH average) | Minimal data dependency; top-20 basket composition maintenance burden not justified for initial deployment. |

---

## Part VI — Additional State / Struct Additions Required

The following fields must be added to the structs in Doc 3 to support all resolutions above. These are not new behaviors — they are missing initializations or tracking fields for logic already specified.

**`TradeState` additions:**
- `stall_band_counter: int = 0` (I-6)
- `expiry_tightened: bool = False` (I-6)
- `trap_moved_away: bool = False` (II-7)

**`PortfolioState` additions:**
- `effective_max_heat: float = CONFIG.MAX_HEAT_PCT` (II-11, must be kept in sync by `update_heat_cooloff`)
- `capitulation_tranches_deployed: dict[str, int] = {}` (III-3)

**`TradeJournalEntry` additions:**
- `cdc_qualifies_zero_tolerance: bool | None = None` (II-4)

**`PivotFlag` additions:**
- `first_reaction_confirmed: bool = False` (II-2)

**`SetupCandidate` additions:**
- `deep_pullback_consolidation_confluence: bool = False` (II-6)

---

*End of Consolidated Build Specification*
