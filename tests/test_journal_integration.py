"""
test_journal_integration.py
============================
End-to-end test: runs a synthetic scenario through the full pipeline and asserts
that a complete, correctly-populated journal is produced at each decision point.

Scenario:
  1. Setup candidate rejected by heat ceiling → SkippedSetupLogEntry(reason=HEAT_CAP)
  2. CDC candidate (cdc_qualifies_zero_tolerance=True) entry approved → ENTRY event
  3. Drawdown drops 20% → log_event(drawdown_tier_change) for TIER_1 then TIER_2
  4. Time expiry tightens stop → log_event(STOP_MOVED, expiry_tightened)
  5. Trade closes via expiry → TradeJournalEntry with cdc_qualifies_zero_tolerance=True
  6. Capitulation event → log_event(capitulation_detected + capitulation_tranche_deployed)
"""
import pytest
from datetime import datetime, timezone, timedelta
from bot.structs import (
    PortfolioState, TradeState, DrawdownTier, Direction,
    SetupCandidate, SetupType, SetupClass, ManagementMode,
    EventType, TradeJournalEntry, SkippedSetupLogEntry,
)
from bot.config import (
    MAX_HEAT_PCT, EXPIRY_CONTINUATION_BARS, CAPITULATION_DRAWDOWN_LOOKBACK_BARS,
)
from bot.portfolio.heat import enforce_portfolio_heat
from bot.portfolio.drawdown import check_drawdown_tier
from bot.portfolio.capitulation import check_capitulation
from bot.trade_management.lifecycle import update_trade
from bot.trade_management.expiry import check_time_expiry


def _make_cdc_candidate(cdc_zt: bool = True):
    c = SetupCandidate(
        asset="BTC",
        direction=Direction.UP,
        trigger_price=100.0,
        stop_price=90.0,
        conviction_score=2,
        setup_type=SetupType.CDC,
        setup_class=SetupClass.CONTINUATION,
    )
    c.cdc_qualifies_zero_tolerance = cdc_zt
    return c


def _make_trade(trade_id="T1", setup_type=SetupType.CDC, cdc_zt: bool = True) -> TradeState:
    t = TradeState(
        id=trade_id,
        asset="BTC",
        direction=Direction.UP,
        setup_type=setup_type,
        setup_class=SetupClass.CONTINUATION,
        management_mode=ManagementMode.AGGRESSIVE,
        entry_price=100.0,
        stop_price=90.0,
        targets=[115.0, 130.0],
        initial_risk_usd=2000.0,
        position_size=200.0,
        initial_position_size=200.0,
        is_open=True,
    )
    t.cdc_qualifies_zero_tolerance = cdc_zt
    return t


def _make_liq_spike(z=3.0, window=480):
    import random; random.seed(7)
    base = [1.0 + random.gauss(0, 0.1) for _ in range(window)]
    mean = sum(base) / len(base)
    std = (sum((x - mean)**2 for x in base) / len(base)) ** 0.5
    return base + [mean + z * std]


def _make_oi_decline(days=7, decline=0.30):
    bars = days * 24
    oi = 1000.0
    s = [oi] * (bars + 1)
    s[-1] = oi * (1.0 - decline)
    return s


def _make_closes(dd=0.25, n=None):
    n = n or CAPITULATION_DRAWDOWN_LOOKBACK_BARS
    return [100.0] * (n - 1) + [100.0 * (1 - dd)]


# ──────────────────────────────────────────────────────────────────

def test_full_journal_scenario():
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)

    portfolio = PortfolioState(
        equity=100_000.0,
        equity_ath=100_000.0,
    )
    portfolio.effective_max_heat = MAX_HEAT_PCT
    portfolio.fund_balances["capitulation_reserve"] = 20_000.0

    trade_journal: list[TradeJournalEntry] = []
    skipped_journal: list[SkippedSetupLogEntry] = []
    event_journal: list[dict] = []

    # ── Step 1: Heat ceiling rejection ────────────────────────────────────────
    # Fill portfolio to 5.5% heat
    blocker = TradeState(asset="ETH", initial_risk_usd=5500.0, position_size=1)
    portfolio.open_trades["BLOCKER"] = blocker

    # Candidate wants 2% more → total 7.5% > 6% ceiling
    cand = _make_cdc_candidate()
    candidate_trade = TradeState(asset="BTC", initial_risk_usd=2000.0, position_size=1)
    blocked = enforce_portfolio_heat(
        portfolio, candidate_trade,
        skipped_journal=skipped_journal,
        candidate=cand,
        now=now,
    )
    assert blocked is True
    assert len(skipped_journal) == 1
    skip = skipped_journal[0]
    assert skip.reason == "HEAT_CAP"
    assert skip.asset == "BTC"
    assert skip.setup_type == SetupType.CDC
    assert skip.cdc_qualifies_zero_tolerance is True   # II-4

    # ── Step 2: Approved trade entry ──────────────────────────────────────────
    # Free up heat
    portfolio.open_trades = {}
    trade = _make_trade("CDC_T1", cdc_zt=True)
    portfolio.open_trades["CDC_T1"] = trade

    # Log entry event manually (normally done by backtest engine at entry time)
    from bot.journaling.writer import log_event
    log_event(EventType.ENTRY, {"entry_price": trade.entry_price}, event_journal, trade, now)
    entry_events = [e for e in event_journal if e["event_type"] == "ENTRY"]
    assert len(entry_events) == 1
    assert entry_events[0]["entry_price"] == 100.0
    assert entry_events[0]["trade_id"] == "CDC_T1"

    # ── Step 3: Drawdown tier changes ─────────────────────────────────────────
    # Drop to 10% → TIER_1
    portfolio.equity = 90_000.0
    check_drawdown_tier(portfolio, journal=event_journal)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1
    tier_events = [e for e in event_journal if e.get("detail") == "drawdown_tier_change"]
    assert len(tier_events) == 1
    assert tier_events[0]["new_tier"] == "TIER_1"

    # Drop to 20% → TIER_2
    portfolio.equity = 80_000.0
    check_drawdown_tier(portfolio, journal=event_journal)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_2
    tier_events = [e for e in event_journal if e.get("detail") == "drawdown_tier_change"]
    assert len(tier_events) == 2
    assert tier_events[1]["new_tier"] == "TIER_2"

    # ── Step 4: Expiry tightens stop → STOP_MOVED event ──────────────────────
    atr = 5.0
    # Artificially set bars_in_trade to the tighten threshold
    trade.bars_in_trade = EXPIRY_CONTINUATION_BARS
    price_flat = 100.5  # < EXPIRY_CONTINUATION_ATR_MULT * atr, so still stalling
    check_time_expiry(trade, price_flat, 0, atr, now, journal=event_journal)
    assert trade.expiry_tightened is True
    tighten_events = [e for e in event_journal if e.get("event_type") == "STOP_MOVED" and e.get("reason") == "expiry_tightened"]
    assert len(tighten_events) == 1

    # ── Step 5: Trade closes via expiry → TradeJournalEntry ───────────────────
    # Next bar: still stalling → closes because expiry_tightened is already True
    trade.bars_in_trade += 1
    check_time_expiry(trade, price_flat, 0, atr, now, journal=event_journal)
    # trade is now closed; simulate the backtest engine writing the closed journal entry
    from bot.journaling.writer import log_trade_closed
    log_trade_closed(trade, portfolio, price_flat, now, trade_journal)

    assert len(trade_journal) == 1
    entry = trade_journal[0]
    assert entry.trade_id == "CDC_T1"
    assert entry.asset == "BTC"
    assert entry.setup_type == SetupType.CDC
    assert entry.cdc_qualifies_zero_tolerance is True      # II-4 field populated
    assert entry.drawdown_tier_at_entry == DrawdownTier.TIER_2  # current tier at snapshot
    assert not trade.is_open

    # ── Step 6: Capitulation event ────────────────────────────────────────────
    liq = _make_liq_spike(z=3.0)
    oi = _make_oi_decline(decline=0.30)
    closes = _make_closes(dd=0.25)

    now2 = now + timedelta(days=30)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now2, journal=event_journal)

    cap_events = [e for e in event_journal if e.get("detail") == "capitulation_detected"]
    assert len(cap_events) == 1
    assert cap_events[0]["asset"] == "BTC"

    tranche_events = [e for e in event_journal if e.get("detail") == "capitulation_tranche_deployed"]
    assert len(tranche_events) >= 1
    assert tranche_events[0]["asset"] == "BTC"
    assert tranche_events[0]["new_tranches"] >= 1


def test_lifecycle_emits_journal_events():
    """Confirm update_trade routes CLOSE/PARTIAL/COMPOUND events to the journal."""
    now = datetime(2026, 6, 1, tzinfo=timezone.utc)
    portfolio = PortfolioState(equity=100_000.0, equity_ath=100_000.0)
    portfolio.effective_max_heat = MAX_HEAT_PCT

    trade_journal = []
    event_journal = []

    trade = _make_trade("STOP_TEST", cdc_zt=False)
    trade.stop_price = 95.0

    # Price touches stop → CLOSE via stop_loss
    events = update_trade(
        trade, 94.0, 0, 5.0, now,
        journal=trade_journal,
        portfolio=portfolio,
        event_journal=event_journal,
    )
    assert any(e["action"] == "CLOSE" and e["reason"] == "stop_loss" for e in events)
    assert not trade.is_open
    # TradeJournalEntry should have been written
    assert len(trade_journal) == 1
    assert trade_journal[0].trade_id == "STOP_TEST"
