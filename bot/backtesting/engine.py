"""
engine.py — Event-driven bar-replay loop
========================================

**Spec reference:** Doc-2 §6, §14; Resolution II-4.

Structural fix (post Change 7):
- trend_class now computed from live ADX/ER indicator state instead of
  being hardcoded to TrendClass.TRENDING. This enables the LOCKOUT_TREND
  relative-strength veto in evaluate_entry, which was never firing before.
- update_htf_bias gated to D1 bars only (it is a daily signal).
- trend_class passed into _flush_pending_fills so pending fills also
  respect the current trend classification.
"""
from bot.structs import Direction
from typing import List, Dict, Any, Optional, Set, Tuple
from datetime import datetime, timezone, timedelta
from collections import defaultdict
import logging

from bot.structs import (
    OHLCV_Bar, PortfolioState, TradeState, SetupCandidate,
    TradeJournalEntry, SkippedSetupLogEntry, EventType,
    AssetConfig, BiasState, TrendClass, MarketBasket, SetupType
)
from bot.config import (
    ADX_TREND_THRESHOLD,
    ER_TREND_THRESHOLD,
    MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER,
    CONFIG,
)
from bot.data_ingestion.ohlcv_buffer import on_bar_close as buffer_on_bar_close, get_bars
from bot.data_ingestion.feed_manager import feeds, update_oi, update_liquidations
from bot.market_context.htf_bias import update_htf_bias, htf_bias
from bot.market_context.pivot_registry import update_pivot_registry, pivot_registry
from bot.setup_detection.runner import run_setup_detection
from bot.entry_risk.entry_gate import evaluate_entry
from bot.trade_management.lifecycle import update_trade
from bot.portfolio.heat import enforce_portfolio_heat, update_heat_cooloff
from bot.portfolio.drawdown import check_drawdown_tier
from bot.portfolio.capitulation import check_capitulation
from bot.portfolio.ath_realization import check_ath_realization
from bot.journaling.writer import log_event
from bot.indicators.registry import get_or_create as get_indicator_state

logger = logging.getLogger(__name__)

# Dedup key: (asset, timeframe, setup_type, direction, detected_bar_index)
# detected_bar_index anchors to the pivot bar so the same underlying signal
# cannot spawn multiple trades across consecutive detection bars.
_SetupDedupKey = Tuple[str, str, str, str, int]


def _compute_trend_class(state) -> TrendClass:
    """
    Derive TrendClass from live indicator state.
    ADX >= ADX_TREND_THRESHOLD  → LOCKOUT_TREND
    ER  >= ER_TREND_THRESHOLD   → TRENDING
    Otherwise                   → RANGING
    """
    if state.adx >= ADX_TREND_THRESHOLD:
        return TrendClass.LOCKOUT_TREND
    if state.efficiency_ratio >= ER_TREND_THRESHOLD:
        return TrendClass.TRENDING
    return TrendClass.RANGING


class BacktestEngine:
    """
    Orchestrates the backtest pipeline bar-by-bar.
    """

    def __init__(self, initial_equity: float = 100000.0, executor=None, notifier=None):
        self.portfolio = PortfolioState(equity=initial_equity, equity_ath=initial_equity)
        self.executor = executor
        self.notifier = notifier
        self.trade_journal: List[TradeJournalEntry] = []
        self.skipped_journal: List[SkippedSetupLogEntry] = []
        self.event_journal: List[Dict] = []

        self.configs: Dict[str, AssetConfig] = {}
        self.market_basket = MarketBasket()
        self.assets: List[str] = []

        self.equity_history: List[Tuple[datetime, float]] = [
            (datetime.now(timezone.utc), initial_equity)
        ]

        # Dedup registry: prevents the same pivot from spawning multiple trades.
        # Cleared per (asset, tf) stream on each new bar timestamp.
        self._active_setup_keys: Set[_SetupDedupKey] = set()

        # Setups accepted this bar, queued for fill at the NEXT bar's open.
        self._pending_fills: List[SetupCandidate] = []

        # Trades filled this bar — staged here and committed to open_trades
        # AFTER the lifecycle loop, so they cannot be stopped out same-bar.
        self._newly_opened: Dict[str, TradeState] = {}

        # Track the last bar timestamp per (asset, tf) for dedup key clearing.
        self._last_bar_ts: Dict[Tuple[str, str], datetime] = {}

        # Running peak equity and max drawdown for correct stats.
        self._peak_equity: float = initial_equity
        self._max_drawdown: float = 0.0

    # ------------------------------------------------------------------
    # Configuration
    # ------------------------------------------------------------------

    def add_asset_config(self, config: AssetConfig) -> None:
        self.configs[config.symbol] = config
        if config.symbol not in self.assets:
            self.assets.append(config.symbol)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _dedup_key(self, cand: SetupCandidate) -> _SetupDedupKey:
        return (
            cand.asset,
            cand.timeframe,
            cand.setup_type.name if cand.setup_type else "",
            cand.direction.name if cand.direction else "",
            cand.detected_bar_index,
        )

    @staticmethod
    def _apply_cluster_pnl_scaling(
        trade: TradeState,
        newly_opened: Dict[str, TradeState],
    ) -> None:
        """
        Change 12: scale P&L sizing for same-bar same-direction clusters.
        _heat_risk_usd must already be frozen at the pre-scale admission value.
        """
        mode = CONFIG.get("CLUSTER_PNL_SCALING_MODE", "off")
        if mode == "off":
            return

        peers = sum(
            1 for t in newly_opened.values()
            if t.direction == trade.direction
        )
        n = peers + 1
        if mode == "cap2":
            n = min(n, 2)
        if n <= 1:
            return

        scale = 1.0 / n
        trade.position_size *= scale
        trade.initial_position_size *= scale
        trade.initial_risk_usd *= scale

    def _flush_pending_fills(self, bar: OHLCV_Bar, trend_class: TrendClass) -> None:
        """
        Fill setups queued from the previous bar at this bar's open.
        New trades are staged in self._newly_opened and committed to
        open_trades only AFTER the lifecycle loop, so they cannot be
        stopped out on the same bar they were filled.

        trend_class is passed in from step() so fills respect the current
        trend classification — previously this was hardcoded to TRENDING here.
        """
        if not self._pending_fills:
            return

        fill_price = bar.open
        now = bar.timestamp

        still_pending: List[SetupCandidate] = []
        for cand in self._pending_fills:
            if cand.asset != bar.asset or cand.timeframe != bar.timeframe:
                still_pending.append(cand)
                continue

            bars = get_bars(cand.asset, cand.timeframe, 100)
            bar_idx = len(get_bars(cand.asset, cand.timeframe, 100000))
            atr_state = get_indicator_state(cand.asset, cand.timeframe)
            atr = atr_state.atr_14 if atr_state.atr_14 else 0.0
            current_bias = htf_bias.get(cand.asset, BiasState.NEUTRAL)

            asset_24h_change = 0.0
            if len(bars) >= 24:
                asset_24h_change = (
                    (bars[-1].close - bars[-24].close) / bars[-24].close
                )

            cand.trigger_price = fill_price

            res = evaluate_entry(
                candidate=cand,
                htf_bias=current_bias,
                trend_class=trend_class,       # live value, not hardcoded
                market_basket=self.market_basket,
                asset_24h_change=asset_24h_change,
                account_equity=self.portfolio.equity,
                atr=atr,
                drawdown_tier=self.portfolio.drawdown_tier,
                bars_for_percentile=bars,
                bar_index=bar_idx,
                now=now,
            )

            if res.trade:
                res.trade.entry_price = fill_price
                # Freeze full admission risk for heat caps; decoupled from any later
                # P&L scaling (Change 10 v3). Must use post-conviction sizing from
                # evaluate_entry — pre-scoring mock sizing was always 0.
                res.trade._heat_risk_usd = res.trade.initial_risk_usd

                # Gate: skip isolated MD entries when configured.
                # A peer is any same-direction trade that entered within ±3 H1 bars.
                if (
                    MOMENTUM_DIVERGENCE_REQUIRE_CLUSTER
                    and res.trade.setup_type == SetupType.MOMENTUM_DIVERGENCE
                ):
                    peer_window = timedelta(hours=3)  # 3 × H1 = 3 hours
                    all_open = {**self.portfolio.open_trades, **self._newly_opened}
                    has_peer = any(
                        t.direction == res.trade.direction
                        and t.entry_timestamp is not None
                        and abs(t.entry_timestamp - now) <= peer_window
                        for t in all_open.values()
                    )
                    if not has_peer:
                        from bot.structs import SkippedSetupLogEntry
                        self.skipped_journal.append(SkippedSetupLogEntry(
                            candidate_id=cand.id,
                            asset=cand.asset,
                            timeframe=cand.timeframe,
                            setup_type=cand.setup_type,
                            direction=cand.direction,
                            rejected_at=now,
                            reason="MD_NO_CLUSTER_PEER",
                            conviction_score=res.trade.conviction_score,
                        ))
                        continue

                # ── Heat check and fill for ALL accepted trades ──────────────
                # (MD trades reach here only after passing the cluster gate above)
                # enforce_portfolio_heat returns True when heat is BREACHED (skip).
                heat_breached = enforce_portfolio_heat(
                    self.portfolio, res.trade,
                    skipped_journal=self.skipped_journal,
                    candidate=cand,
                    now=now,
                    pending_trades=self._newly_opened,
                )
                if heat_breached:
                    continue

                self._apply_cluster_pnl_scaling(res.trade, self._newly_opened)
                res.trade.entry_timestamp = now
                self._newly_opened[res.trade.id] = res.trade
                
                # --- LIVE EXECUTION / NOTIFICATION ---
                if self.executor:
                    self.executor.submit_market_order(
                        asset=res.trade.asset,
                        side="buy" if res.trade.direction == Direction.UP else "sell",
                        qty=res.trade.position_size
                    )
                    self.executor.submit_stop_order(
                        asset=res.trade.asset,
                        side="sell" if res.trade.direction == Direction.UP else "buy",
                        qty=res.trade.position_size,
                        stop_price=res.trade.stop_price
                    )
                if self.notifier:
                    self.notifier.alert_trade_opened(
                        setup_type=res.trade.setup_type.name,
                        direction=res.trade.direction.name,
                        entry_price=res.trade.entry_price,
                        stop_price=res.trade.stop_price,
                        size=res.trade.position_size
                    )

        # Write back candidates belonging to other bars/timeframes so they are
        # retried on their matching bar (Bug 2: still_pending was never stored).
        self._pending_fills = still_pending

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    def step(self, bar: OHLCV_Bar, oi: float = 0.0, liq: float = 0.0) -> None:
        """Process one bar close."""
        asset = bar.asset
        tf    = bar.timeframe
        now   = bar.timestamp

        # ── 1. Update feeds and OHLCV buffer first so indicators are fresh
        if oi > 0:
            update_oi(asset, oi)
        if liq > 0:
            update_liquidations(asset, liq)

        buffer_on_bar_close(bar)

        if asset not in self.configs:
            self.portfolio.open_trades.update(self._newly_opened)
            self._newly_opened = {}
            return

        config = self.configs[asset]

        # ── 2. Update market context
        # HTF bias is a D1 signal — only recompute on D1 bars
        if tf == "D1":
            update_htf_bias(asset)
        update_pivot_registry(asset, tf)

        bars = get_bars(asset, tf, 100)
        if not bars:
            self.portfolio.open_trades.update(self._newly_opened)
            self._newly_opened = {}
            return

        all_pivots = pivot_registry.get(asset, {}).get(tf, [])

        # Keep only pivots recent enough to have bars within the detection window
        # bars[0].timestamp is the oldest bar in our 100-bar window
        if bars:
            cutoff = bars[0].timestamp
            pivots = [p for p in all_pivots if p.timestamp >= cutoff]
        else:
            pivots = all_pivots
        state        = get_indicator_state(asset, tf)
        atr          = state.atr_14 if state.atr_14 is not None else 0.0
        current_bias = htf_bias.get(asset, BiasState.NEUTRAL)

        # ── 3. Compute trend class from live indicator state
        #       Previously hardcoded to TrendClass.TRENDING — this meant the
        #       LOCKOUT_TREND veto in evaluate_entry never fired, allowing
        #       counter-trend entries during strong trending moves.
        trend_class = _compute_trend_class(state)

        # ── 4. Fill pending setups at this bar's open, now that trend_class
        #       is available. Staged in _newly_opened, not yet in open_trades.
        self._flush_pending_fills(bar, trend_class)

        # Clear dedup keys for this (asset, tf) stream on each new bar
        bar_key: Tuple[str, str] = (asset, tf)
        if self._last_bar_ts.get(bar_key) != now:
            self._active_setup_keys = {
                k for k in self._active_setup_keys
                if k[0] != asset or k[1] != tf
            }
            self._last_bar_ts[bar_key] = now

        # ── 5. Lifecycle for trades already open BEFORE this bar
        #       (_newly_opened are not in open_trades yet — cannot be stopped
        #        out on the same bar they were filled)
        current_price = bar.close
        bar_idx       = len(get_bars(asset, tf, 100000))

        for trade_id in list(self.portfolio.open_trades.keys()):
            trade = self.portfolio.open_trades[trade_id]
            if trade.asset == asset and trade.timeframe == tf:
                update_trade(
                    trade, current_price, bar_idx, atr, now,
                    self.trade_journal, self.portfolio, self.event_journal,
                    executor=self.executor, notifier=self.notifier
                )

                if not trade.is_open:
                    del self.portfolio.open_trades[trade_id]
                    is_loss = trade.realized_r < 0
                    update_heat_cooloff(self.portfolio, is_loss)

                    pnl = trade.realized_r * trade.initial_risk_usd
                    self.portfolio.equity += pnl
                    self.equity_history.append((now, self.portfolio.equity))

                    # Update running peak and max drawdown
                    if self.portfolio.equity > self._peak_equity:
                        self._peak_equity = self.portfolio.equity
                    dd = (self._peak_equity - self.portfolio.equity) / self._peak_equity
                    if dd > self._max_drawdown:
                        self._max_drawdown = dd

        # ── 6. Commit newly filled trades — visible to lifecycle from next bar
        self.portfolio.open_trades.update(self._newly_opened)
        self._newly_opened = {}

        # ── 7. Portfolio state updates
        check_drawdown_tier(self.portfolio, self.event_journal)

        equity_30d_ago  = self.portfolio.equity
        now_ms = now.timestamp() * 1000 if isinstance(now, datetime) else now
        thirty_days_ago_ms = now_ms - 30 * 86400 * 1000
        for t, eq in reversed(self.equity_history):
            t_ms = t.timestamp() * 1000 if isinstance(t, datetime) else t
            if t_ms <= thirty_days_ago_ms:
                equity_30d_ago = eq
                break
        check_ath_realization(self.portfolio, equity_30d_ago, now)

        if asset in feeds:
            feed = feeds[asset]
            daily_closes = [b.close for b in get_bars(asset, "D1", 100)]
            if daily_closes:
                check_capitulation(
                    self.portfolio, asset, daily_closes,
                    feed.liq_hourly, feed.oi_hourly, now, self.event_journal,
                )

        # ── 8. Setup detection
        candidates = run_setup_detection(
            bars, pivots, atr, config, feeds.get(asset), self.market_basket, trend_class
        )

        # ADD THIS
        import logging
        _dbg = logging.getLogger("debug")
        
        all_open_trades = {**self.portfolio.open_trades, **self._newly_opened}
        total_open_risk_usd = sum(
            t._heat_risk_usd if t._heat_risk_usd > 0 else t.initial_risk_usd
            for t in all_open_trades.values()
        )
        current_heat = total_open_risk_usd / self.portfolio.equity if self.portfolio.equity > 0 else 0.0
        
        _dbg.info(f"BAR {bar.timestamp} | candidates={len(candidates)} | "
                  f"open_trades={len(self.portfolio.open_trades)} | "
                  f"heat={current_heat:.4f} | "
                  f"htf_bias={current_bias}")
        for c in candidates:
            # Temporary calculate conviction for accurate logging (will be overwritten in evaluate_entry next bar)
            from bot.entry_risk.conviction import compute_conviction_score
            compute_conviction_score(c, current_bias, bars)
            _dbg.info(f"  CANDIDATE: {c.setup_type} {c.direction} | conviction={c.conviction_score}")

        # ── 9. Dedup and queue accepted candidates for next-bar fill
        for cand in candidates:
            key = self._dedup_key(cand)
            if key in self._active_setup_keys:
                continue

            # Suppress if an identical open trade already exists
            already_open = any(
                t.asset == asset
                and t.timeframe == tf
                and t.direction == cand.direction
                and t.setup_type == cand.setup_type
                for t in self.portfolio.open_trades.values()
            )
            if already_open:
                continue

            self._active_setup_keys.add(key)
            self._pending_fills.append(cand)

    # ------------------------------------------------------------------
    # Stats
    # ------------------------------------------------------------------

    def get_summary_stats(self) -> Dict[str, Any]:
        trades = self.trade_journal
        total_trades = len(trades)

        if total_trades == 0:
            return {"total_trades": 0}

        wins     = sum(1 for t in trades if t.realized_r > 0)
        win_rate = wins / total_trades
        avg_r    = sum(t.realized_r for t in trades) / total_trades

        by_type: Dict[str, int] = defaultdict(int)
        for t in trades:
            name = t.setup_type.name if t.setup_type else "UNKNOWN"
            by_type[name] += 1

        skipped_reasons: Dict[str, int] = defaultdict(int)
        for s in self.skipped_journal:
            skipped_reasons[s.reason] += 1

        # Loss breakdown by time held
        quick_losses = 0
        for t in trades:
            if t.realized_r <= -0.95 and t.exit_timestamp and t.entry_timestamp:
                entry_ms = t.entry_timestamp.timestamp() * 1000 if hasattr(t.entry_timestamp, "timestamp") else t.entry_timestamp
                exit_ms = t.exit_timestamp.timestamp() * 1000 if hasattr(t.exit_timestamp, "timestamp") else t.exit_timestamp
                if (exit_ms - entry_ms) / 1000 <= 3600 * 3:
                    quick_losses += 1

        # Per-setup win rate and avg R
        by_type_wr: Dict[str, Dict] = {}
        for t in trades:
            name = t.setup_type.name if t.setup_type else "UNKNOWN"
            if name not in by_type_wr:
                by_type_wr[name] = {"wins": 0, "losses": 0, "total_r": 0.0}
            if t.realized_r > 0:
                by_type_wr[name]["wins"] += 1
            else:
                by_type_wr[name]["losses"] += 1
            by_type_wr[name]["total_r"] += t.realized_r

        return {
            "total_trades":      total_trades,
            "win_rate":          round(win_rate, 4),
            "avg_r":             round(avg_r, 4),
            "max_drawdown_pct":  round(self._max_drawdown * 100, 4),
            "trades_by_type":    dict(by_type),
            "skipped_reasons":   dict(skipped_reasons),
            "quick_losses":      quick_losses,
            "by_type_wr":        by_type_wr,
        }