"""
drawdown.py — Drawdown tier transitions
=========================================

**Spec reference:** Doc-1 §8.4; Doc-3 check_drawdown_tier pseudocode.
Resolution I-10: intermediate recovery step (tier-2 → tier-1 at hysteresis midpoint).
Resolution II-13: consecutive_losses early-warning — already in Doc-3, no gap.
"""
from __future__ import annotations
import logging
from typing import List, Optional

from bot.structs import PortfolioState, DrawdownTier, EventType
from bot.config import (
    DRAWDOWN_TIER_1_PCT,
    DRAWDOWN_TIER_2_PCT,
    DRAWDOWN_TIER_3_PCT,
    DRAWDOWN_RECOVERY_HYSTERESIS,
    HEAT_COOLOFF_LOSS_STREAK
)

logger = logging.getLogger(__name__)

def check_drawdown_tier(portfolio: PortfolioState, journal: Optional[List] = None) -> None:
    """
    Evaluate and update portfolio.drawdown_tier.

    Downgrade path:
      equity < ATH × (1 - DRAWDOWN_TIER_1_PCT)  → TIER_1
      equity < ATH × (1 - DRAWDOWN_TIER_2_PCT)  → TIER_2
      equity < ATH × (1 - DRAWDOWN_TIER_3_PCT)  → TIER_3
      consecutive_losses >= HEAT_COOLOFF_LOSS_STREAK → max(current, TIER_1)  [II-13 early warning]

    Recovery path (Resolution I-10):
      TIER_3 → TIER_2 when equity >= ATH × (1 - DRAWDOWN_TIER_3_PCT × DRAWDOWN_RECOVERY_HYSTERESIS)
      TIER_2 → TIER_1 when equity >= ATH × (1 - DRAWDOWN_TIER_2_PCT × DRAWDOWN_RECOVERY_HYSTERESIS)
      TIER_1 → TIER_0 when equity >= ATH × (1 - 0.05)  [within 5% of ATH, i.e. TIER_1_PCT * HYSTERESIS]
    """
    if portfolio.equity <= 0 or portfolio.equity_ath <= 0:
        return

    current_dd_pct = (portfolio.equity_ath - portfolio.equity) / portfolio.equity_ath
    
    # Start from current tier to ensure we don't drop tiers without hitting hysteresis
    new_tier = portfolio.drawdown_tier

    # 1. Evaluate pure drawdown downgrade
    # If the drawdown actively breaches a lower threshold, immediately drop into that tier
    if current_dd_pct >= DRAWDOWN_TIER_3_PCT:
        new_tier = max(new_tier, DrawdownTier.TIER_3, key=lambda t: t.value)
    elif current_dd_pct >= DRAWDOWN_TIER_2_PCT:
        new_tier = max(new_tier, DrawdownTier.TIER_2, key=lambda t: t.value)
    elif current_dd_pct >= DRAWDOWN_TIER_1_PCT:
        new_tier = max(new_tier, DrawdownTier.TIER_1, key=lambda t: t.value)

    # 2. Evaluate consecutive losses early warning (II-13)
    if portfolio.consecutive_losses >= HEAT_COOLOFF_LOSS_STREAK:
        new_tier = max(new_tier, DrawdownTier.TIER_1, key=lambda t: t.value)

    # 3. Evaluate hysteresis recovery paths
    # Can cascade recovery if multiple hysteresis levels are cleared (e.g. huge jump in equity)
    if new_tier == DrawdownTier.TIER_3:
        if current_dd_pct <= DRAWDOWN_TIER_3_PCT * DRAWDOWN_RECOVERY_HYSTERESIS:
            new_tier = DrawdownTier.TIER_2
            
    if new_tier == DrawdownTier.TIER_2:
        if current_dd_pct <= DRAWDOWN_TIER_2_PCT * DRAWDOWN_RECOVERY_HYSTERESIS:
            new_tier = DrawdownTier.TIER_1

    if new_tier == DrawdownTier.TIER_1:
        # Cannot recover to TIER_0 if forced into TIER_1 by consecutive losses
        if portfolio.consecutive_losses < HEAT_COOLOFF_LOSS_STREAK:
            if current_dd_pct <= DRAWDOWN_TIER_1_PCT * DRAWDOWN_RECOVERY_HYSTERESIS:
                new_tier = DrawdownTier.TIER_0

    if new_tier != portfolio.drawdown_tier:
        logger.info(
            "Drawdown tier transitioned from %s to %s (DD: %.2f%%, Losses: %d)",
            portfolio.drawdown_tier.name, new_tier.name,
            current_dd_pct * 100, portfolio.consecutive_losses
        )
        if journal is not None:
            from bot.journaling.writer import log_event
            log_event(
                EventType.SKIPPED,
                {
                    "detail": "drawdown_tier_change",
                    "old_tier": portfolio.drawdown_tier.name,
                    "new_tier": new_tier.name,
                    "dd_pct": round(current_dd_pct * 100, 2),
                    "consecutive_losses": portfolio.consecutive_losses,
                },
                journal,
            )
        portfolio.drawdown_tier = new_tier
