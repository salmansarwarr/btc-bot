import logging
from bot.config import PAPER_TRADING
from typing import Dict, Any, Optional
import time
import uuid

# Setup dedicated orders logger
order_logger = logging.getLogger("orders")
order_logger.setLevel(logging.INFO)
fh = logging.FileHandler("orders.log")
fh.setFormatter(logging.Formatter("%(asctime)s | %(levelname)s | %(message)s"))
order_logger.addHandler(fh)

def submit_market_order(asset: str, side: str, qty: float) -> Optional[Dict[str, Any]]:
    """Submit a market order."""
    if PAPER_TRADING:
        order_id = f"synth_{uuid.uuid4().hex[:8]}"
        order_logger.info(f"PAPER MARKET | {asset} | {side} | qty: {qty} | id: {order_id}")
        return {"id": order_id, "status": "closed", "filled": qty, "type": "market"}
    
    # Real ccxt logic would go here
    order_logger.info(f"LIVE MARKET | {asset} | {side} | qty: {qty}")
    return None

def submit_stop_order(asset: str, side: str, qty: float, stop_price: float) -> Optional[Dict[str, Any]]:
    """Submit a stop market order."""
    if PAPER_TRADING:
        order_id = f"synth_stop_{uuid.uuid4().hex[:8]}"
        order_logger.info(f"PAPER STOP | {asset} | {side} | qty: {qty} | stop: {stop_price:.2f} | id: {order_id}")
        return {"id": order_id, "status": "open", "type": "stop"}
    
    # Real ccxt logic would go here
    order_logger.info(f"LIVE STOP | {asset} | {side} | qty: {qty} | stop: {stop_price:.2f}")
    return None

def cancel_order(order_id: str) -> bool:
    """Cancel an open order."""
    if PAPER_TRADING:
        order_logger.info(f"PAPER CANCEL | id: {order_id}")
        return True
    
    # Real ccxt logic would go here
    order_logger.info(f"LIVE CANCEL | id: {order_id}")
    return True
