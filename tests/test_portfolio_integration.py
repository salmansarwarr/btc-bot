"""
test_portfolio_integration.py
==============================
Integration test: simulates a sequence of trades and market conditions including
wins/losses, a drawdown period, a capitulation event, and an ATH period.

Verifies that heat, drawdown tier, and capitulation tranches all update
correctly and don't conflict with each other.
"""
import pytest
from datetime import datetime, timezone, timedelta
from bot.structs import (
    PortfolioState, TradeState, DrawdownTier, Direction
)
from bot.config import (
    MAX_HEAT_PCT, HEAT_COOLOFF_LOSS_STREAK, HEAT_COOLOFF_REDUCTION,
    DRAWDOWN_TIER_1_PCT, DRAWDOWN_TIER_2_PCT,
    DRAWDOWN_RECOVERY_HYSTERESIS,
    DRAWDOWN_TIER_1_RISK_MULT,
    CAPITULATION_TRANCHE_SIZE, CAPITULATION_TRANCHE_DROP_PCT,
    CAPITULATION_DRAWDOWN_LOOKBACK_BARS,
    LIQ_SIGMA_THRESHOLD, OI_DECLINE_PCT_7D, MEGA_WIPE_PRICE_DRAWDOWN,
    ATH_GAIN_PCT_30D, ATH_REALIZATION_PCT,
    ATH_BACKSTOP_DAYS, ATH_BACKSTOP_PCT, ATH_BACKSTOP_PROXIMITY_PCT,
)
from bot.portfolio.heat import enforce_portfolio_heat, update_heat_cooloff
from bot.portfolio.drawdown import check_drawdown_tier
from bot.portfolio.capitulation import (
    compute_liquidation_zscore, compute_oi_decline_pct,
    compute_price_drawdown_pct, check_capitulation,
    deploy_capitulation_reserve_tranche,
)
from bot.portfolio.ath_realization import check_ath_realization
from bot.entry_risk.sizer import compute_position_size


def _make_trade(asset: str, risk_usd: float, direction: Direction = Direction.UP) -> TradeState:
    return TradeState(
        asset=asset, direction=direction,
        entry_price=100.0, stop_price=90.0,
        initial_risk_usd=risk_usd,
        position_size=risk_usd / 10,   # 10-dollar stop
        initial_position_size=risk_usd / 10,
        is_open=True,
    )

def _make_liq_spike_series(window: int = 480, z_target: float = 3.0) -> list:
    import random
    random.seed(0)
    baseline = [1.0 + random.gauss(0, 0.1) for _ in range(window)]
    mean = sum(baseline) / len(baseline)
    std = (sum((x - mean) ** 2 for x in baseline) / len(baseline)) ** 0.5
    current = mean + z_target * std
    return baseline + [current]

def _make_oi_decline_series(days: int = 7, decline: float = 0.30) -> list:
    bars = days * 24
    oi_prior = 1000.0
    oi_now = oi_prior * (1.0 - decline)
    series = [oi_prior] * (bars + 1)
    series[-1] = oi_now
    return series

def _make_price_series(drawdown: float, bars: int = None) -> list:
    bars = bars or CAPITULATION_DRAWDOWN_LOOKBACK_BARS
    recent_high = 100.0
    current_close = recent_high * (1.0 - drawdown)
    return [recent_high] * (bars - 1) + [current_close]


# ──────────────────────────────────────────────────────────────────
# Phase 1 → Phase 4 integration test
# ──────────────────────────────────────────────────────────────────

def test_portfolio_lifecycle_integration():
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    portfolio = PortfolioState(
        equity=100_000.0,
        equity_ath=100_000.0,
    )
    portfolio.effective_max_heat = MAX_HEAT_PCT  # 6%
    portfolio.fund_balances["capitulation_reserve"] = 20_000.0
    portfolio.last_realization_date = now

    # ── Phase 1: Normal operations — a few winning trades ──────────────────────
    # Open a trade: BTC, $2k risk (2% heat)
    t_btc = _make_trade("BTC", risk_usd=2000.0)
    portfolio.open_trades["T1"] = t_btc
    assert not enforce_portfolio_heat(portfolio, _make_trade("ETH", risk_usd=2000.0))  # 4% total → pass

    # Win: close T1 profitably
    portfolio.open_trades.pop("T1")
    update_heat_cooloff(portfolio, trade_closed_as_loss=False)
    assert portfolio.consecutive_losses == 0
    assert portfolio.effective_max_heat == MAX_HEAT_PCT

    # ── Phase 2: Loss streak → heat cooloff + tier-1 entry warning ─────────────
    for _ in range(HEAT_COOLOFF_LOSS_STREAK):
        update_heat_cooloff(portfolio, trade_closed_as_loss=True)

    expected_heat = MAX_HEAT_PCT * (1.0 - HEAT_COOLOFF_REDUCTION)
    assert portfolio.consecutive_losses == HEAT_COOLOFF_LOSS_STREAK
    assert portfolio.effective_max_heat == pytest.approx(expected_heat)

    # A 5% trade should now be blocked (floor is 4.5%)
    big_trade = _make_trade("ETH", risk_usd=5000.0)  # 5% of 100k
    assert enforce_portfolio_heat(portfolio, big_trade) == True

    # A smaller 3% trade should still pass
    small_trade = _make_trade("ETH", risk_usd=3000.0)  # 3% of 100k
    assert enforce_portfolio_heat(portfolio, small_trade) == False

    # ── Phase 3: Equity drawdown → tier transitions ────────────────────────────
    portfolio.consecutive_losses = 0
    portfolio.effective_max_heat = MAX_HEAT_PCT  # reset losses

    # Drop 10% → TIER_1
    portfolio.equity = 90_000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1

    # Sizer now halves risk: a conviction-2 trade should yield half the normal size
    from bot.structs import SetupCandidate
    cand = SetupCandidate(
        asset="BTC", direction=Direction.UP,
        trigger_price=100.0, stop_price=90.0, conviction_score=2
    )
    size_normal = compute_position_size(cand, 100_000.0, DrawdownTier.TIER_0)
    size_tier1  = compute_position_size(cand, 100_000.0, DrawdownTier.TIER_1)
    assert size_tier1 == pytest.approx(size_normal * DRAWDOWN_TIER_1_RISK_MULT)

    # Drop 20% → TIER_2 (trading halted)
    portfolio.equity = 80_000.0
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_2
    size_tier2 = compute_position_size(cand, 100_000.0, DrawdownTier.TIER_2)
    assert size_tier2 == 0.0

    # Recovery with hysteresis: must pass 50% of TIER_2 threshold to step to TIER_1
    # TIER_2_PCT * HYSTERESIS = 20% * 0.5 = 10% DD → equity must reach 90k
    portfolio.equity = 89_000.0  # 11% DD — still not through hysteresis
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_2

    portfolio.equity = 90_000.0  # exactly 10% DD — clears hysteresis → TIER_1
    check_drawdown_tier(portfolio)
    assert portfolio.drawdown_tier == DrawdownTier.TIER_1

    # ── Phase 4: Capitulation event ────────────────────────────────────────────
    portfolio.equity_ath = 100_000.0  # still tracking the original ATH
    reserve_before = portfolio.fund_balances["capitulation_reserve"]  # 20k

    liq = _make_liq_spike_series(z_target=3.0)     # z >= 2.0 ✓
    oi  = _make_oi_decline_series(decline=0.30)     # 30% decline ≥ 25% ✓
    closes = _make_price_series(drawdown=0.25)      # 25% DD ≥ 20% ✓

    now += timedelta(days=30)
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)

    assert portfolio.capitulation_detected_date is not None
    # At 25% DD: tranches_earned = int(0.25 / 0.10) = 2 → 2 tranches deployed
    tranches_deployed = portfolio.capitulation_tranches_deployed.get("BTC", 0)
    assert tranches_deployed == 2

    # Verify reserve reduced, active balance increased
    reserve_after = portfolio.fund_balances["capitulation_reserve"]
    active_after  = portfolio.fund_balances["active"]
    assert reserve_after < reserve_before
    assert active_after > 0

    # deploy_capitulation_reserve_tranche fires both tranches in one call:
    # amount = reserve * CAPITULATION_TRANCHE_SIZE * new_tranches
    # = 20k * 0.25 * 2 = 10k
    expected_deployed = reserve_before * CAPITULATION_TRANCHE_SIZE * 2
    assert reserve_before - reserve_after == pytest.approx(expected_deployed, rel=1e-6)

    # No double-deploy: calling again at same drawdown fires nothing
    portfolio_reserve_snapshot = portfolio.fund_balances["capitulation_reserve"]
    check_capitulation(portfolio, "BTC", closes, liq, oi, now)
    assert portfolio.fund_balances["capitulation_reserve"] == portfolio_reserve_snapshot

    # A bigger drawdown (30% → 3rd tranche) should deploy
    closes_deeper = _make_price_series(drawdown=0.32)
    check_capitulation(portfolio, "BTC", closes_deeper, liq, oi, now)
    assert portfolio.capitulation_tranches_deployed["BTC"] == 3

    # ── Phase 5: ATH period — equity recovers and triggers profit-taking ───────
    portfolio.equity = 130_000.0
    portfolio.equity_ath = 100_000.0
    now += timedelta(days=1)
    equity_30d_ago = 100_000.0  # 30% gain

    check_ath_realization(portfolio, equity_30d_ago, now)

    # Primary trigger: 30% gain → 10% realized to reserve
    expected_realized = 130_000.0 * ATH_REALIZATION_PCT
    reserve_final = portfolio.fund_balances["capitulation_reserve"]
    assert reserve_final > 0
    assert portfolio.equity == pytest.approx(130_000.0 - expected_realized)

    # ── Phase 6: Heat is respected even during capitulation ───────────────────
    # Capitulation-deployed funds go to the active pool, not bypassing the heat ceiling.
    # Confirm: adding a trade when portfolio is already at heat ceiling gets blocked.
    portfolio.equity = 100_000.0
    portfolio.effective_max_heat = MAX_HEAT_PCT
    portfolio.open_trades = {}

    t1 = _make_trade("BTC", risk_usd=2000.0)  # 2%
    t2 = _make_trade("ETH", risk_usd=2000.0)  # 2%
    t3 = _make_trade("SOL", risk_usd=2000.0)  # 2% → total = 6% = ceiling
    portfolio.open_trades["T1"] = t1
    portfolio.open_trades["T2"] = t2
    portfolio.open_trades["T3"] = t3

    # Any new trade is blocked — even during capitulation regime
    new_trade = _make_trade("LINK", risk_usd=100.0)
    assert enforce_portfolio_heat(portfolio, new_trade) == True

    # Closing one trade frees up room
    portfolio.open_trades.pop("T3")
    assert enforce_portfolio_heat(portfolio, new_trade) == False
