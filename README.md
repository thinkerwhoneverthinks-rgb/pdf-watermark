# 📋 Daily Target Tracker Telegram Bot

A production-ready Telegram Bot built with **Python 3.11+**, **aiogram 3.x**, and a **Telegram Mini App (WebApp)** interface that tracks daily study targets with **zero external database**. All state lives inside a pinned Telegram message, making it resilient across server restarts, redeployments, and Render free-tier sleep cycles.

---

## ✨ Features

### 1️⃣ Three Flexible Ways to Add Targets

* **📱 Telegram Mini App (WebApp UI) [Recommended]**
  * Sleek interactive UI matching your Telegram client's theme.
  * **Subject Selection**: Physics, Chemistry, Biology, Test, or custom subject names.
  * **Chapter / Topic Name**: Tag targets with specific chapters (e.g., *Thermodynamics*, *Rotational Motion*).
  * **Task Types**:
    * **Lecture**: Automatically splits counts into individual numbered tasks (`Lecture 1 (Thermodynamics)`, `Lecture 2 (Thermodynamics)`).
    * **Questions**: Sets target question count with dynamic fraction tracking (`(0/50)`).
    * **Revision / Short Notes / NCERT**: Direct one-click topic additions.
    * **Custom**: Add custom tasks with custom descriptions.
  * **Multi-Target Staging**: Add multiple tasks to a pending list and submit them all simultaneously with **"🚀 Send All Targets"**.

* **⚡ Quick Syntax (`/target` or `/q`)**
  * Superfast target creation using short commands.
  * **Example:**
    ```text
    /target phy L2 Q50 ncert Thermodynamics
    ```
    *Generates:*
    - Lecture 1 (Thermodynamics)
    - Lecture 2 (Thermodynamics)
    - Questions (Thermodynamics) (0/50)
    - NCERT (Thermodynamics)
  * Supports `/target` or `/q` aliases.

* **📝 Direct Multiline Plain Text**
  * Send unformatted or structured study targets directly into the chat:
    ```text
    CHEM
    LECTURE - 2 lec
    QUESTION - DPP 5
    ```

---

### 2️⃣ Interactive Checklist & Real-Time Sync

* **Dual-Sync Mirroring**: Checklist is published to both your private DM and your study group/forum topic. Tapping a task in either location updates both messages instantly.
* **Interactive Question Tracking**: Increment solved questions interactively directly from inline buttons.
* **Test Score Recording**: Tap `[📝 Enter Score]` to input exam/mock test results (e.g., `620/720`) with instant synchronization.
* **Rate-Limit Safe**: Built-in handling for `TelegramRetryAfter` backoff to prevent API throttling during fast clicks.

---

### 3️⃣ Telegram-as-a-Database (Zero External DB)

* **No Postgres/MySQL/Redis needed**: All persistent state is serialized as JSON and stored inside a pinned state message (`DTT_STATE_V1::`) in your administrative storage chat.
* **Auto-Pruning**: Automatically cleans up target history older than 14 days and manages state payload length to stay strictly within Telegram's 4096-character limit.
* **Stateless Resilience**: Bot recovers full state on startup even when container environments sleep or restart.

---

### 4️⃣ Render & Cloud Ready

* Built-in lightweight `aiohttp` server listening on `$PORT`.
* Health endpoints: `GET /` and `GET /health` returning `200 OK` for continuous uptime monitoring on Render, Railway, or Fly.io.

---

## 🏗️ Repository Architecture

```text
├── .gitignore
├── README.md                 # Project documentation
├── config.py                 # Central environment & runtime configuration
├── handlers/
│   ├── __init__.py
│   ├── fsm_entry.py          # /start, /help, /target, /q, & WebApp data handling
│   ├── sync_callbacks.py     # Inline button callbacks, task toggling & scores
│   └── vision_entry.py       # Plain text & multiline target parser
├── index.html                # Telegram WebApp (Mini App) frontend
├── main.py                   # Bot bootstrap & aiohttp health check server
├── requirements.txt          # Python dependencies
└── storage.py                # Telegram-as-a-database engine & message renderer
```

---

## ⚙️ Configuration (.env)

Create a `.env` file or define these environment variables in your deployment dashboard:

| Variable | Required | Description |
| :--- | :---: | :--- |
| `BOT_TOKEN` | **Yes** | Telegram Bot API token from [@BotFather](https://t.me/BotFather) |
| `BOT_OWNER_ID` | **Yes** | Your personal Telegram user ID (used as admin and state host) |
| `GROUP_CHAT_ID` | No | Target group chat ID (e.g., `-100xxxxxxxxxx`) for group mirroring |
| `TOPIC_THREAD_ID`| No | Forum topic thread ID inside the group |
| `WEBAPP_URL` | No | Public HTTPS URL where `index.html` is hosted (e.g., GitHub Pages) |
| `STATE_CHAT_ID` | No | Chat ID hosting the state message (defaults to `BOT_OWNER_ID`) |
| `STATE_TOPIC_ID`| No | Forum topic ID for the state chat if applicable |
| `PORT` | No | Health check server port (default: `8080`, provided automatically on Render) |

---

## 🚀 Local Development

1. **Clone the repository:**
   ```bash
   git clone https://github.com/thinkerwhoneverthinks-rgb/pdf-watermark.git
   cd pdf-watermark
   ```

2. **Create and activate a virtual environment:**
   ```bash
   python -m venv venv
   # Linux/macOS:
   source venv/bin/activate
   # Windows:
   .\venv\Scripts\activate
   ```

3. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

4. **Set environment variables** in a `.env` file:
   ```env
   BOT_TOKEN=123456789:ABCDefghIJKLmnOPQRstuvWXYZ
   BOT_OWNER_ID=123456789
   GROUP_CHAT_ID=-1001234567890
   TOPIC_THREAD_ID=2
   WEBAPP_URL=https://yourusername.github.io/pdf-watermark/
   ```

5. **Run the bot:**
   ```bash
   python main.py
   ```

---

## 🌐 Setting Up the Telegram WebApp (Mini App)

1. Host `index.html` on **GitHub Pages**, **Vercel**, or **Cloudflare Pages** (HTTPS is required by Telegram).
   * *Tip for GitHub Pages:* Go to repository **Settings** → **Pages** → select `main` branch `/ (root)` and click **Save**.
2. Open [@BotFather](https://t.me/BotFather) on Telegram:
   * Run `/setmenubutton`
   * Select your bot
   * Provide your WebApp URL (`https://yourusername.github.io/pdf-watermark/`) and a button title (e.g., `Add Targets 🎯`).
3. Set `WEBAPP_URL` in your `.env` so `/start` and `/help` also provide the WebApp launch button directly.

---

## ☁️ Deployment on Render (Free Web Service)

1. Push your changes to the `main` branch.
2. Log in to [Render Dashboard](https://dashboard.render.com/) and click **New +** → **Web Service**.
3. Connect your GitHub repository.
4. Set the build and run settings:
   * **Runtime**: `Python 3`
   * **Build Command**: `pip install -r requirements.txt`
   * **Start Command**: `python main.py`
   * **Instance Type**: `Free`
5. Under **Environment Variables**, add:
   * `BOT_TOKEN`
   * `BOT_OWNER_ID`
   * `GROUP_CHAT_ID` (optional)
   * `TOPIC_THREAD_ID` (optional)
   * `WEBAPP_URL` (optional)
6. Click **Deploy Web Service**.
   * Render runs the bot and automatically polls `GET /` on `$PORT` to keep health status healthy.

---

## 📌 Usage Commands Summary

| Command / Input | Scope | Description |
| :--- | :---: | :--- |
| `/start` or `/help` | Private DM | Displays interactive guide and launch button for WebApp |
| `/target <syntax>` | Private DM | Quick command parsing (e.g. `/target phy L2 Q50 ncert`) |
| `/q <syntax>` | Private DM | Alias for `/target` |
| Direct Multiline Text | Private DM | Parses raw subject and study target blocks |
| WebApp Button | Private DM | Opens full visual builder for multi-target entry |

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
