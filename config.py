"""Central configuration for the Daily Target Tracker bot.

All secrets and deployment-specific values are read from environment
variables so the same codebase runs locally and on Render unchanged.
"""

import os

from dotenv import load_dotenv

load_dotenv()

# --- Telegram ---
BOT_TOKEN: str = os.getenv("BOT_TOKEN", "")
if not BOT_TOKEN:
    raise RuntimeError("BOT_TOKEN environment variable is not set")

# Group where the daily summary is posted (e.g. -100xxxxxxxxxx)
GROUP_CHAT_ID: int = int(os.getenv("GROUP_CHAT_ID", "0"))
# Forum topic id inside that group for the summary
TOPIC_THREAD_ID: int = int(os.getenv("TOPIC_THREAD_ID", "0"))

# URL for the Telegram WebApp (Mini App) UI
WEBAPP_URL: str = os.getenv("WEBAPP_URL", "")

# --- Telegram-as-a-database ---
# Admin Telegram user id (optional)
BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", "0"))
STATE_CHAT_ID: int = int(os.getenv("STATE_CHAT_ID", str(BOT_OWNER_ID)))
STATE_TOPIC_ID: int = int(os.getenv("STATE_TOPIC_ID", "0"))
STATE_MARKER: str = "DTT_STATE_V1::"
STATE_MAX_LEN: int = 3900  # Telegram message limit is 4096; keep headroom
STATE_RETENTION_DAYS: int = 14

# --- Render ---
PORT: int = int(os.getenv("PORT", "8080"))
