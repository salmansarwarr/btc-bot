"""
market_context — HTF bias, trend classification, and pivot registry
====================================================================

**Spec references:**
  - Doc-1 §1.2  (trend classification — ADX + ER)
  - Doc-1 §1.3  (HTF directional bias — factual MSB + EMA50 veto)
  - Doc-3        (update_htf_bias, update_pivot_registry pseudocode)
  - Resolution I-1  (N_HTF_BIAS_LOOKBACK enforced in detect_factual_msb)
  - Resolution I-2  (EMA50_SLOPE_LAG_BARS for veto)
  - Resolution II-1 (PIVOT_PERCENTILE_SCORING_ENABLED — percentile at scoring, not detection)
  - Resolution II-2 (first_reaction_confirmed tracking on PivotFlag)

Responsibilities
----------------
- Run ``update_htf_bias`` on each D1 close.
- Classify trend state (RANGING / TRENDING / LOCKOUT_TREND) per timeframe.
- Maintain the pivot registry: detect fractals, assign MAJOR/MINOR strength,
  track first-contact reactions for minor pivots (II-2).
- Expose ``detect_factual_msb(asset, timeframe, lookback_bars)`` with the
  lookback parameter mandated by Resolution I-1.

Sub-modules (to be implemented)
--------------------------------
  htf_bias.py         — update_htf_bias, detect_factual_msb(lookback_bars)
  trend.py            — trend classification (ADX gate + ER trigger, II-1)
  pivot_registry.py   — fractal detection, strength assignment, reaction tracking
  structure_break.py  — MSB / Break-of-Structure utilities shared across modules
"""
