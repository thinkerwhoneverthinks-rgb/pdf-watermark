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

# Group where the mirrored checklist is posted (e.g. -100xxxxxxxxxx)
GROUP_CHAT_ID: int = int(os.getenv("GROUP_CHAT_ID", "0"))
# Forum topic id inside that group
TOPIC_ID: int = int(os.getenv("TOPIC_ID", "0"))

# --- Telegram-as-a-database ---
# Chat that hosts the pinned JSON state message. Defaults to the admin DM.
BOT_OWNER_ID: int = int(os.getenv("BOT_OWNER_ID", "0"))
STATE_CHAT_ID: int = int(os.getenv("STATE_CHAT_ID", str(BOT_OWNER_ID)))
if STATE_CHAT_ID == 0:
    raise RuntimeError("Set BOT_OWNER_ID (admin Telegram user id) or STATE_CHAT_ID")
STATE_TOPIC_ID: int = int(os.getenv("STATE_TOPIC_ID", "0"))
STATE_MARKER: str = "DTT_STATE_V1::"
STATE_MAX_LEN: int = 3900  # Telegram message limit is 4096; keep headroom
STATE_RETENTION_DAYS: int = 14

# --- Gemini ---
GEMINI_API_KEY: str = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL: str = os.getenv("GEMINI_MODEL", "gemini-2.5-flash")

# --- Render ---
PORT: int = int(os.getenv("PORT", "8080"))
