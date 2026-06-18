"""
backtesting — Event-replay engine and performance metrics
=========================================================

**Spec references:**
  - Doc-2 §6      (post-hoc CDC Proxy A vs. B quality/frequency comparison via journal)
  - Doc-2 §14     (heat cooloff effectiveness analysable from journal R-series)
  - Doc-2 Add. A  (100+ journal entries before revisiting conviction weighting)
  - Resolution II-4 (cdc_qualifies_zero_tolerance enables Proxy A vs. B backtest split)

Responsibilities
----------------
- Replay historical OHLCV + feed data through the full bot pipeline.
- Call the same detect_*, evaluate_entry, and trade-management functions used live.
- Collect TradeJournalEntry and SkippedSetupLogEntry outputs.
- Compute performance metrics: total R, win rate, max drawdown, Sharpe proxy,
  conviction-tier breakdown, CDC Proxy-A vs. B win-rate comparison.

Sub-modules (to be implemented)
--------------------------------
  engine.py           — event-driven bar-replay loop
  data_loader.py      — load historical OHLCV + feed CSVs / parquet files
  metrics.py          — aggregate statistics from journal entries
  report.py           — human-readable HTML / Markdown report generator
"""
