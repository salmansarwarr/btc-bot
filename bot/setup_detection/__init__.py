"""
setup_detection — Setup detector functions
==========================================

**Spec references:**
  - Doc-1 §2.x  (all setup types)
  - Doc-3        (run_setup_detection, detect_* pseudocode)
  - Resolution I-7   (detect_cdc handles both CDC and PATTERN_FAILURE via include_pattern_failure flag)
  - Resolution II-5  (SHALLOW_ATR_CAP_MULT wired into detect_shallow_pullback)
  - Resolution II-6  (deep_pullback_consolidation_confluence field on SetupCandidate)
  - Resolution II-15 (RSI_DIV_EXTREME_LOW/HIGH gate in detect_momentum_divergence)
  - Resolution III-10 (CONSOLIDATION_* params in detect_consolidation_entry)

Responsibilities
----------------
- Implement one detector function per SetupType.
- Return ``List[SetupCandidate]`` (empty list if no setup found on that bar).
- ``run_setup_detection(asset, timeframe)`` orchestrates all detectors in the
  correct order and returns the merged candidate list.

Sub-modules (to be implemented)
--------------------------------
  sfp.py                  — detect_sfp (Swing Failure Pattern)
  cdc.py                  — detect_cdc(include_pattern_failure=False)
                            Resolution I-7: single function, direction inverted when flag=True
  msb_pullback.py         — detect_msb_shallow, detect_msb_deep
                            Resolution II-5: ATR cap in shallow; II-6: confluence field in deep
  open_drive.py           — detect_open_drive
  consolidation.py        — detect_consolidation_entry (Resolution III-10)
  momentum_divergence.py  — detect_momentum_divergence (Resolution II-15 extreme-zone gate)
  liquidation_flush.py    — detect_liquidation_flush (Resolution I-9 renamed per-asset version)
  runner.py               — run_setup_detection(asset, timeframe) orchestrator
"""
