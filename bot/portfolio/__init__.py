"""
portfolio — Portfolio-level risk management and fund allocation
==============================================================

**Spec references:**
  - Doc-1 §8.x  (ATH realization, drawdown tiers, capitulation reserve)
  - Doc-3        (enforce_portfolio_heat, update_heat_cooloff, check_drawdown_tier,
                  check_ath_realization, check_capitulation pseudocode)
  - Resolution I-9   (portfolio-level check_capitulation vs. per-asset; distinct function names)
  - Resolution I-10  (intermediate drawdown recovery: tier-2 → tier-1 at 50% hysteresis)
  - Resolution II-9  (Mega Wipe dual gate — already in Doc-3; no gap)
  - Resolution II-10 (ATH backstop proximity guard: equity ≥ ATH × (1 - ATH_BACKSTOP_PROXIMITY_PCT))
  - Resolution II-11 (enforce_portfolio_heat uses PortfolioState.effective_max_heat, not CONFIG directly)
  - Resolution II-13 (consecutive_losses early-warning — already in Doc-3; no gap)
  - Resolution III-2 (correlation_bucket(asset) — static mapping from CORRELATION_BUCKETS config)
  - Resolution III-3 (deploy_capitulation_reserve_tranche — 25% per -10% drop)

Responsibilities
----------------
- Enforce heat caps (hard ceiling via effective_max_heat; per-bucket correlated cap).
- Update effective_max_heat on each loss/win (heat cooloff soft reduction).
- Evaluate drawdown tier transitions with hysteresis recovery (I-10).
- Detect ATH conditions and realize profits to cash / capitulation reserve.
- Detect Mega Wipe / capitulation and deploy reserve tranches (III-3).

Sub-modules (to be implemented)
--------------------------------
  heat.py             — enforce_portfolio_heat, update_heat_cooloff
                        BUG FIX (II-11): reference PortfolioState.effective_max_heat
  drawdown.py         — check_drawdown_tier (with intermediate recovery step I-10)
  ath_realization.py  — check_ath_realization (with proximity guard II-10)
  capitulation.py     — check_capitulation, deploy_capitulation_reserve_tranche (III-3)
  correlation.py      — correlation_bucket(asset) static lookup (III-2)
"""
