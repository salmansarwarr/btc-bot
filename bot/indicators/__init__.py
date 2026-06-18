"""
indicators — Technical indicator computation
============================================

**Spec references:**
  - Doc-3 §1 (Indicators registry — IndicatorState)
  - Resolution I-2 (EMA-50 slope lag via ema_50_buffer)
  - Resolution II-15 (RSI extreme-zone thresholds RSI_DIV_EXTREME_LOW/HIGH)
  - Resolution III-6 (ema_50_at_lag — rolling buffer approach selected)

Responsibilities
----------------
- Compute and update ``IndicatorState`` on each bar close for every
  registered (asset, timeframe) pair.
- Expose helper accessors (``ema_50_at_lag``) consumed by market-context logic.

Sub-modules (to be implemented)
--------------------------------
  ema.py      — exponential moving average (period 50; buffer updated here)
  atr.py      — average true range (period 14; canonical volatility unit)
  rsi.py      — relative strength index (period 14)
  adx.py      — average directional index
  er.py       — Kaufman Efficiency Ratio (TREND_CONFIRM_BARS window)
  registry.py — ``Indicators[asset][timeframe]`` dict management
"""
