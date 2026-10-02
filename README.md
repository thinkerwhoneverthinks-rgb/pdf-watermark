# 📋 Daily Target Tracker Bot

A production-ready Telegram bot (aiogram 3.x + Google Gemini) that tracks daily
study targets with **zero external database** — all state lives inside a pinned
Telegram message, so it survives Render free-tier sleeps and redeploys.

## Features

- **Guided `/new` flow** (aiogram FSM): subject → chapter → task type →
  dynamic lecture splitting → optional note → dual dispatch.
- **Handwritten target recognition**: send a photo, Gemini Vision extracts
  structured JSON targets and splits `count > 1` items into numbered buttons.
- **Dual-sync mirroring**: the checklist is posted to your DM *and* the group
  topic; tapping a button in either place updates both instantly
  (rate-limit-safe via `TelegramRetryAfter` handling).
- **Test scores**: `[📝 Enter Score]` → type `610/720` in DM → both messages
  update to `[✅ Scored: 610/720]` and a celebration is posted to the topic.
- **Render-ready**: lightweight `aiohttp` server on `$PORT` with `GET /`
  and `GET /health` returning 200.

## Architecture

```
config.py               environment configuration
storage.py              Telegram-as-a-database (pinned JSON state message)
handlers/fsm_entry.py   guided step-by-step /new flow (FSM)
handlers/vision_entry.py photo -> Gemini Vision -> structured targets
handlers/sync_callbacks.py toggles + dual-sync edits + score entry
main.py                 bot + health server, run concurrently via asyncio
```

State message: the bot pins a message starting with `DTT_STATE_V1::` in the
state chat (default: the admin's DM). **Do not delete or unpin it.**

## Local setup

```bash
python -m venv venv && source venv/bin/activate
pip install -r requirements.txt

export BOT_TOKEN="123:abc"           # from @BotFather
export BOT_OWNER_ID="123456789"      # your Telegram user id (state store host)
export GROUP_CHAT_ID="-100xxxxxxxxxx"
export TOPIC_ID="12345"              # forum topic id
export GEMINI_API_KEY="AIza..."      # https://aistudio.google.com
python main.py
```

## Deploy on Render (Free Web Service)

1. Push this folder to a GitHub repo.
2. Render Dashboard → **New → Web Service** → connect the repo.
3. Configure:
   - **Build Command**: `pip install -r requirements.txt`
   - **Start Command**: `python main.py`
   - **Instance type**: Free
4. Add the environment variables listed above (Render injects `PORT` itself).
5. Deploy. Render's health checks hit `GET /` on `$PORT`; the bot polls
   Telegram concurrently in the same process.

> **Notes**
> - Free-tier services sleep after inactivity; when Render wakes the bot it
>   re-reads the pinned state message, so nothing is lost.
> - If the state chat is a group, make the bot an admin so it can pin.
> - The bot prunes target dates older than 14 days automatically to stay
>   within Telegram's 4096-char message limit.
