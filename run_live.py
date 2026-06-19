"""
run_live.py — Entry point for the live trading engine.

Usage:
  python3 run_live.py
"""
import sys
import logging
from bot.live.engine import LiveEngine

# Set up root logger
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)s | %(levelname)s | %(message)s"
)
logger = logging.getLogger("main")

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Run a single bar and exit")
    args = parser.parse_args()

    logger.info("Starting live trading engine initialization...")
    
    # Initialize the live engine for BTC/USDT spot
    engine = LiveEngine(asset="BTC/USDT", timeframe="1h")
    
    try:
        # Start the core loop
        engine.run(dry_run=args.dry_run)
    except KeyboardInterrupt:
        logger.info("Received KeyboardInterrupt. Shutting down gracefully...")
        sys.exit(0)
    except Exception as e:
        logger.fatal(f"Fatal error in live engine: {e}", exc_info=True)
        sys.exit(1)

if __name__ == "__main__":
    main()
