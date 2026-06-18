"""Change 10 v3 diagnostic — confirm _heat_risk_usd field and heat accounting."""
from __future__ import annotations

import dataclasses
import sys
from collections import Counter

from bot.structs import TradeState, PortfolioState
from bot.portfolio.heat import enforce_portfolio_heat


def section(title: str) -> None:
    print(f"\n{'=' * 60}")
    print(title)
    print("=" * 60)


def check_struct_field() -> None:
    section("1. TradeState dataclass field")
    fields = {f.name for f in dataclasses.fields(TradeState)}
    print(f"_heat_risk_usd in dataclass fields: {'_heat_risk_usd' in fields}")
    t = TradeState(asset="BTC", initial_risk_usd=3000.0)
    print(f"default _heat_risk_usd: {t._heat_risk_usd}")
    t._heat_risk_usd = 3000.0
    print(f"after assignment: {t._heat_risk_usd}")


def check_heat_logic() -> None:
    section("2. enforce_portfolio_heat behavior")
    cand = TradeState(asset="BTC", initial_risk_usd=4000.0)

    portfolio_ok = PortfolioState(equity=100_000.0)
    portfolio_ok.open_trades["T1"] = TradeState(
        id="T1", asset="BTC", initial_risk_usd=5000.0, _heat_risk_usd=5000.0
    )
    blocked_ok = enforce_portfolio_heat(portfolio_ok, cand)
    print(f"open _heat_risk_usd=5000, cand 4000 → blocked={blocked_ok} (expect True)")

    portfolio_bad = PortfolioState(equity=100_000.0)
    portfolio_bad.open_trades["T1"] = TradeState(
        id="T1", asset="BTC", initial_risk_usd=5000.0
    )
    blocked_bad = enforce_portfolio_heat(portfolio_bad, cand)
    print(
        f"open initial_risk=5000 but _heat_risk_usd=0 → blocked={blocked_bad} "
        f"(expect False — heat invisible)"
    )


def check_engine_stamping() -> None:
    section("3. Engine fill stamping (monkey-patch)")
    from bot.backtesting import engine as engine_mod

    orig_flush = engine_mod.BacktestEngine._flush_pending_fills
    fill_log: list[dict] = []

    def wrapped_flush(self, bar, trend_class):
        before = id(self._flush_pending_fills)
        orig_flush(self, bar, trend_class)
        for tid, trade in self._newly_opened.items():
            fill_log.append(
                {
                    "id": tid[:8],
                    "initial_risk_usd": trade.initial_risk_usd,
                    "_heat_risk_usd": trade._heat_risk_usd,
                    "match": trade._heat_risk_usd == trade.initial_risk_usd,
                }
            )

    engine_mod.BacktestEngine._flush_pending_fills = wrapped_flush

    from bot.portfolio import heat as heat_mod

    heat_calls = Counter()
    heat_zero_open = 0

    orig_heat = heat_mod.enforce_portfolio_heat

    def wrapped_heat(portfolio, trade, skipped_journal=None, candidate=None, now=None, pending_trades=None):
        all_open = {**portfolio.open_trades, **(pending_trades or {})}
        if all_open:
            if all(t._heat_risk_usd == 0.0 for t in all_open.values()):
                nonlocal heat_zero_open
                heat_zero_open += 1
        result = orig_heat(portfolio, trade, skipped_journal, candidate, now, pending_trades)
        if result:
            heat_calls["blocked"] += 1
            if skipped_journal and candidate is not None:
                reason = skipped_journal[-1].reason if skipped_journal else "?"
                heat_calls[f"blocked:{reason}"] += 1
        else:
            heat_calls["allowed"] += 1
        return result

    heat_mod.enforce_portfolio_heat = wrapped_heat

    # Run pinned-window backtest via run_backtest.main
    import run_backtest

    run_backtest.main()

    print(f"Heat checks with ALL open _heat_risk_usd=0: {heat_zero_open}")
    print(f"Heat call counts: {dict(heat_calls)}")
    print(f"Fills logged: {len(fill_log)}")
    if fill_log:
        zero_heat = sum(1 for f in fill_log if f["_heat_risk_usd"] == 0.0)
        mismatch = sum(1 for f in fill_log if not f["match"])
        print(f"Fills with _heat_risk_usd=0: {zero_heat}")
        print(f"Fills where _heat_risk_usd != initial_risk_usd: {mismatch}")
        print("First 5 fills:")
        for row in fill_log[:5]:
            print(f"  {row}")
        print("Last 5 fills:")
        for row in fill_log[-5:]:
            print(f"  {row}")


if __name__ == "__main__":
    check_struct_field()
    check_heat_logic()
    if "--full" in sys.argv:
        check_engine_stamping()
    else:
        print("\n(Pass --full to run instrumented backtest — fetches live data)")
