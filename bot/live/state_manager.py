import json
import os
import time
import logging
from datetime import datetime
from typing import Dict, Any, List

logger = logging.getLogger(__name__)
STATE_FILE = "live_state.json"

import base64
import pickle

def save_state(engine, last_bar_timestamp):
    """Serialize system state to disk safely."""
    
    # Normalize timestamp — accept either datetime or int ms
    if isinstance(last_bar_timestamp, datetime):
        ts_serializable = last_bar_timestamp.isoformat()
    else:
        ts_serializable = last_bar_timestamp

    # We serialize basic metadata and safely pickle the entire portfolio state
    portfolio_b64 = base64.b64encode(pickle.dumps(engine.portfolio)).decode('utf-8')
    journal_b64 = base64.b64encode(pickle.dumps(engine.trade_journal)).decode('utf-8')
            
    state = {
        "last_bar_timestamp": ts_serializable,
        "portfolio_b64": portfolio_b64,
        "journal_b64": journal_b64,
        "saved_at": int(time.time() * 1000)
    }
    
    with open(STATE_FILE, "w") as f:
        json.dump(state, f, indent=2)
    logger.debug(f"State saved at {ts_serializable}")

def load_state(max_age_ms: int = 7200000) -> Dict[str, Any]:
    """Load system state if it exists and is fresh enough (default 2 hours)."""
    if not os.path.exists(STATE_FILE):
        return None
        
    try:
        with open(STATE_FILE, "r") as f:
            state = json.load(f)
            
        now = int(time.time() * 1000)
        age = now - state.get("saved_at", 0)
        
        if age > max_age_ms:
            logger.warning(f"State file is too old ({age}ms). Discarding.")
            return None
            
        logger.info(f"Loaded valid state from {state.get('last_bar_timestamp')}")
        return state
    except Exception as e:
        logger.error(f"Failed to load state: {e}")
        return None

def restore_engine_state(engine, state_dict: Dict[str, Any]):
    """Restore the portfolio and active trades into the engine."""
    import base64
    import pickle
    
    if "portfolio_b64" in state_dict:
        engine.portfolio = pickle.loads(base64.b64decode(state_dict["portfolio_b64"]))
        logger.info(f"Restored portfolio. Open trades: {len(engine.portfolio.open_trades)}")
        
    if "journal_b64" in state_dict:
        engine.trade_journal = pickle.loads(base64.b64decode(state_dict["journal_b64"]))
        logger.info(f"Restored trade journal. Total trades: {len(engine.trade_journal)}")
