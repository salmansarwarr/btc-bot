import time
import logging
from datetime import datetime, timezone, timedelta
import ccxt
from typing import List

from bot.backtesting.engine import BacktestEngine
from bot.structs import AssetConfig, OHLCV_Bar
from bot.config import EXCHANGE_BASE_URL
from bot.live.state_manager import save_state, load_state, restore_engine_state
import bot.live.executor as executor
import bot.live.notifier as notifier

logger = logging.getLogger("live_engine")
logging.basicConfig(level=logging.INFO, format="%(asctime)s | %(name)s | %(levelname)s | %(message)s")

class LiveEngine:
    def __init__(self, asset: str = "BTC/USDT", timeframe: str = "1h"):
        self.asset = asset
        self.timeframe = timeframe
        self.exchange = ccxt.binance()
        
        if "testnet.binance.vision" in EXCHANGE_BASE_URL:
            self.exchange.set_sandbox_mode(True)
        
        self.engine = BacktestEngine(initial_equity=100_000.0, executor=executor, notifier=notifier) # Start with paper equity
        self.engine.add_asset_config(AssetConfig(symbol="BTC", active_timeframes=["H1", "D1"]))
        
    def fetch_historical_bars(self, limit: int = 750) -> List[OHLCV_Bar]:
        """Fetch historical bars for warmup."""
        logger.info(f"Fetching {limit} historical bars for warmup...")
        # Placeholder for real ccxt fetch_ohlcv implementation
        ohlcv = self.exchange.fetch_ohlcv(self.asset, self.timeframe, limit=limit)
        bars = []
        for row in ohlcv:
            dt = datetime.fromtimestamp(row[0] / 1000.0, tz=timezone.utc)
            bars.append(OHLCV_Bar(
                asset=self.asset.split("/")[0],
                timeframe="H1",
                timestamp=dt,
                open=row[1], high=row[2], low=row[3], close=row[4], volume=row[5]
            ))
        return bars
        
    def warmup(self):
        """Prime the indicators and state using historical data."""
        state = load_state()
        
        # Always fetch historical bars to prime indicators
        bars = self.fetch_historical_bars(limit=750)
        logger.info("Running warmup pass on historical data...")
        
        # We temporarily disable execution hooks during warmup to avoid duplicate logs/alerts
        old_executor = self.engine.executor
        old_notifier = self.engine.notifier
        self.engine.executor = None
        self.engine.notifier = None
        
        for b in bars:
            self.engine.step(b, oi=0.0, liq=0.0)
            
        self.engine.executor = old_executor
        self.engine.notifier = old_notifier
        logger.info("Warmup complete. Indicators primed.")
        
        if state:
            logger.info("Resuming from saved state to restore active portfolio...")
            restore_engine_state(self.engine, state)

    def monitor_guidelines(self):
        """Enforce Phase 2 Paper Trading Guidelines (from tuning_changelog.md)"""
        stats = self.engine.get_summary_stats()
        trades = self.engine.trade_journal
        
        # 1. System Circuit Breaker
        max_dd = stats.get("max_drawdown_pct", 0)
        
        # Calculate 30-day rolling AvgR
        now_sec = time.time()
        thirty_days_ago_ms = now_sec * 1000 - (30 * 86400 * 1000)
        recent_trades = []
        for t in trades:
            if t.exit_timestamp:
                exit_ms = t.exit_timestamp.timestamp() * 1000 if hasattr(t.exit_timestamp, "timestamp") else t.exit_timestamp
                if exit_ms > thirty_days_ago_ms:
                    recent_trades.append(t)
        
        if recent_trades:
            rolling_avg_r = sum(t.realized_r for t in recent_trades) / len(recent_trades)
            if rolling_avg_r < 0.10 and len(recent_trades) >= 10: # give it a minimum sample before pausing
                msg = f"🛑 CIRCUIT BREAKER TRIPPED: 30-day AvgR is {rolling_avg_r:.2f} (Below +0.10). Engine paused."
                logger.error(msg)
                notifier.alert_error(msg)
                import sys; sys.exit(1)
                
        if max_dd > 15.0:
            msg = f"🛑 CIRCUIT BREAKER TRIPPED: Max Drawdown is {max_dd:.2f}% (Exceeds 15.0%). Engine paused."
            logger.error(msg)
            notifier.alert_error(msg)
            import sys; sys.exit(1)
            
        # 2. CDC Watchlist Probation
        cdc_trades = [t for t in trades if t.setup_type and t.setup_type.name == "CDC"]
        if len(cdc_trades) >= 25:
            cdc_avg_r = sum(t.realized_r for t in cdc_trades) / len(cdc_trades)
            if cdc_avg_r < 0:
                msg = f"⚠️ CDC PROBATION BREACHED: {len(cdc_trades)} trades with {cdc_avg_r:.2f} AvgR. Flag for removal."
                logger.warning(msg)
                notifier.alert_error(msg)

    def run(self, dry_run=False):
        """Main live loop."""
        self.warmup()
        logger.info("Live engine starting core loop...")
        
        while True:
            try:
                # 1. Sleep until next bar close (SKIP if dry_run)
                if not dry_run:
                    now = datetime.now(timezone.utc)
                    # Next hour boundary
                    next_hour = now.replace(minute=0, second=5, microsecond=0)
                    if now >= next_hour:
                        next_hour = (now + timedelta(hours=1)).replace(minute=0, second=5, microsecond=0)
                    
                    sleep_sec = max(0.0, (next_hour - now).total_seconds())
                    logger.info(f"Sleeping {sleep_sec:.1f}s until next bar close at {next_hour}")
                    time.sleep(sleep_sec)
                else:
                    logger.info("DRY RUN: Skipping sleep, executing one bar immediately.")
                
                # 2. Fetch the just-closed bar
                # We fetch the last 2 bars to ensure we get the fully closed one
                ohlcv = self.exchange.fetch_ohlcv(self.asset, self.timeframe, limit=2)
                closed_row = ohlcv[-2] # The bar that just closed
                
                bar = OHLCV_Bar(
                    asset=self.asset.split("/")[0],
                    timeframe="H1",
                    timestamp=datetime.fromtimestamp(closed_row[0] / 1000.0, tz=timezone.utc),
                    open=closed_row[1], high=closed_row[2], low=closed_row[3], close=closed_row[4], volume=closed_row[5]
                )
                
                logger.info(f"Processing live bar: {bar.timestamp} | Close: {bar.close}")
                
                # 3. Process the bar through the identical engine logic
                self.engine.step(bar, oi=0.0, liq=0.0)
                
                # 4. Enforce Trading Guidelines
                self.monitor_guidelines()
                
                # 5. State Persistence
                save_state(self.engine, bar.timestamp)
                
                if dry_run:
                    logger.info("DRY RUN complete. Exiting.")
                    break
                    
            except Exception as e:
                logger.error(f"Error in live loop: {e}", exc_info=True)
                notifier.alert_error(str(e))
                time.sleep(60) # Sleep before retry on error
