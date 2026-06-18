"""
trade_management — Active-trade lifecycle management
====================================================

**Spec references:**
  - Doc-1 §5.x  (stalling, FTA interaction, compounding)
  - Doc-1 §6.x  (time expiry rules)
  - Doc-3        (check_stalling, check_fta_interaction, check_time_expiry,
                  check_dynamic_r, check_pending_fta_confirmations pseudocode)
  - Resolution I-3  (I-3 clarification comment in check_fta_interaction)
  - Resolution I-5  (EXPIRY_HTF_BASE_BARS × EXPIRY_HTF_MULTIPLIER in check_time_expiry)
  - Resolution I-6  (stall_band_counter, expiry_tightened on TradeState)
  - Resolution II-7 (TRAP re-entry detection branch in check_stalling;
                     trap_moved_away on TradeState; TRAP_REENTRY_ATR_MULT)
  - Resolution II-12 (FTA-break → skip scheduled partial — already implemented in Doc-3)
  - Resolution III-1 (MAX_PENDING_AGE_BARS in check_pending_fta_confirmations)
  - Resolution III-4 (lock_in_1R_stop — defined in entry_risk.helpers, called here)
  - Resolution III-5 (approaching_target — APPROACHING_TARGET_THRESHOLD)

Responsibilities
----------------
- Per-bar update loop for every open TradeState.
- Stalling detection (ATR band counter + TRAP re-entry branch).
- Time-expiry checks for TRAP, CONTINUATION, and HTF_SWING classes.
- FTA interaction: partial exit, compound add, or close on rejection.
- Dynamic R-locking once trade reaches 2R+ progress.
- Pending-FTA-confirmation expiry (MAX_PENDING_AGE_BARS).

Sub-modules (to be implemented)
--------------------------------
  stalling.py         — check_stalling (Proxy A band + Proxy C re-entry for TRAPs)
  expiry.py           — check_time_expiry (TRAP / CONTINUATION / HTF_SWING branches)
  fta_handler.py      — check_fta_interaction, check_pending_fta_confirmations
                        Note (I-3): aggressive mode → close on FTA reject AND compound on FTA break
  dynamic_r.py        — check_dynamic_r (lock_in_1R_stop called from entry_risk.helpers)
  lifecycle.py        — per-bar trade update orchestrator (calls all check_* functions)
"""
