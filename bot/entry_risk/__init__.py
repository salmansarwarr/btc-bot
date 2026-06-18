"""
entry_risk — Entry evaluation, conviction scoring, and stop/size computation
============================================================================

**Spec references:**
  - Doc-1 §3.x  (conviction scoring — equal-weight 3-point scale)
  - Doc-1 §4.x  (stop placement, position sizing)
  - Doc-3        (evaluate_entry, compute_conviction_score, compute_stop pseudocode)
  - Resolution I-3  (management_mode assignment: AGGRESSIVE if score ≤ 2)
  - Resolution I-4  (SR_FLIP_STOP_ATR_MULT — dedicated stop parameter)
  - Resolution I-8  (passes_relative_strength_filter — LOCKOUT_TREND + UP only)
  - Resolution I-9  (renamed: compute_asset_liquidation_zscore vs. portfolio-level)
  - Resolution II-1 (percentile check in compute_conviction_score — scoring only, not detection)
  - Resolution II-2 (MINOR_PIVOT_RESPECTED_BONUS in compute_conviction_score)
  - Resolution II-6 (DEEP_PULLBACK_CONFLUENCE_BONUS in compute_conviction_score)
  - Resolution III-4 (lock_in_1R_stop definition)
  - Resolution III-7 (signed_pnl helper)
  - Doc-2 Additional A (equal-weight scoring retained; weights not needed)

Responsibilities
----------------
- Score each ``SetupCandidate`` and assign ``conviction_score`` + ``management_mode``.
- Gate entry via portfolio heat, drawdown tier, relative-strength filter.
- Compute stop price (SR_FLIP, MSB, or ATR-based depending on setup type).
- Size the position using RISK_PCT_BY_CONVICTION × equity / stop_distance.
- Expose helper utilities: signed_pnl, lock_in_1R_stop, passes_relative_strength_filter.

Sub-modules (to be implemented)
--------------------------------
  conviction.py       — compute_conviction_score (applies all bonus/penalty rules)
  entry_gate.py       — evaluate_entry (heat check, drawdown tier, RS filter, FTA routing)
  stop_calculator.py  — compute_stop (SR_FLIP_STOP_ATR_MULT, MIN_STOP_ATR_MULT)
  sizer.py            — compute_position_size (RISK_PCT_BY_CONVICTION table)
  helpers.py          — signed_pnl, lock_in_1R_stop, compute_progress_to_target,
                        passes_relative_strength_filter, compute_asset_liquidation_zscore
"""
