"""
journaling — Trade and skipped-setup logging
============================================

**Spec references:**
  - Doc-3 §5.x  (TradeJournalEntry, SkippedSetupLogEntry, log_event)
  - Resolution I-8  (log_skipped_setup reason="RELATIVE_STRENGTH_FILTER")
  - Resolution II-4 (cdc_qualifies_zero_tolerance field on TradeJournalEntry)
  - Doc-2 §6      (dual-classification logging for CDC: Proxy A and B recorded)

Responsibilities
----------------
- Write immutable ``TradeJournalEntry`` records on trade close.
- Write ``SkippedSetupLogEntry`` whenever a setup is rejected at any gate.
- Write interim ``EventType`` events (STOP_MOVED, COMPOUNDED, etc.) for audit trail.
- Expose query helpers for backtest and live review (e.g. filter by setup_type,
  compute aggregate R statistics, count CDC Proxy-B qualification rate).

Sub-modules (to be implemented)
--------------------------------
  writer.py       — log_trade_closed, log_skipped_setup, log_event
  queries.py      — journal query / aggregation helpers
  storage.py      — persistence backend (file / DB abstraction)
"""
