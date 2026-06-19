import requests
import logging
from bot.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID

logger = logging.getLogger(__name__)

def send_alert(message: str):
    """Send a lightweight message to Telegram."""
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        logger.warning(f"Telegram not configured. Missed alert: {message}")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": message,
        "parse_mode": "HTML"
    }
    
    try:
        response = requests.post(url, json=payload, timeout=5)
        response.raise_for_status()
    except Exception as e:
        logger.error(f"Failed to send Telegram alert: {e}")

def alert_trade_opened(setup_type: str, direction: str, entry_price: float, stop_price: float, size: float):
    msg = f"🟢 <b>TRADE OPENED</b>\nType: {setup_type}\nDir: {direction}\nEntry: {entry_price:.2f}\nStop: {stop_price:.2f}\nSize: {size}"
    send_alert(msg)

def alert_trade_closed(setup_type: str, direction: str, reason: str, r_multiple: float):
    icon = "🔴" if r_multiple < 0 else "🟢"
    msg = f"{icon} <b>TRADE CLOSED</b>\nType: {setup_type}\nDir: {direction}\nReason: {reason}\nRealized R: {r_multiple:+.2f}"
    send_alert(msg)

def alert_drawdown_tier(tier: int, reduction_pct: float):
    msg = f"⚠️ <b>DRAWDOWN TIER INCREASED</b>\nTier: {tier}\nRisk Reduction: -{reduction_pct*100:.0f}%"
    send_alert(msg)

def alert_error(error_msg: str):
    msg = f"🚨 <b>SYSTEM ERROR</b>\n{error_msg}"
    send_alert(msg)
