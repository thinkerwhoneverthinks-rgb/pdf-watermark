# 📋 Daily Target Tracker Telegram Bot

A production-ready Telegram Bot built with **Python 3.11+**, **aiogram 3.x**, and a **Telegram Mini App (WebApp)** interface that tracks daily study targets with **zero external database**. Supports multiple users and group study rooms simultaneously by persisting each user's state inside their own private pinned Telegram message.

---

## ✨ Features

### 1️⃣ Three Flexible Ways to Add Targets

* **📱 Telegram Mini App (WebApp UI) [Recommended]**
  * Sleek interactive UI matching your Telegram client's theme.
  * **Target Date Selection**: Choose **Today**, **Tomorrow**, or **Custom Date** picker.
  * **Subject Selection**: Physics, Chemistry, Biology, Test, or custom subject names.
  * **Chapter / Topic Name**: Tag targets with specific chapters (e.g., *Thermodynamics*, *Rotational Motion*).
  * **Time Slot Presets & Custom Tags**: Set study windows (Morning, Afternoon, Evening, Night, or custom e.g., `1-6 PM`, `till 6`) per task.
  * **Task Types**:
    * **Lecture**: Automatically splits counts into individual numbered tasks (`Lecture 1 (Thermodynamics)`, `Lecture 2 (Thermodynamics)`).
    * **Questions**: Sets target question count with dynamic fraction tracking (`(0/81)`).
    * **Revision / Short Notes / NCERT**: Direct one-click topic additions.
    * **Custom**: Add custom tasks with custom descriptions.
  * **Multi-Target Staging**: Add multiple tasks to a pending list and submit them all simultaneously with **"🚀 Send All Targets"**.

* **⚡ Quick Syntax (`/target` or `/q`)**
  * Superfast target creation using short commands with optional date prefix and time slot tags.
  * **Examples:**
    ```text
    /target phy L2 Q50 ncert Thermodynamics
    /target tomorrow phy L2 @morning Q50 @till-6 Thermodynamics
    ```
    *Generates:*
    - Lecture 1 (Thermodynamics) ⏰ *morning*
    - Lecture 2 (Thermodynamics) ⏰ *morning*
    - Questions (Thermodynamics) (0/50) ⏰ *till 6*
    - NCERT (Thermodynamics)
  * Supports `/target` or `/q` aliases.

* **📝 Direct Multiline Plain Text**
  * Send unformatted or structured study targets directly into the chat (with optional `tomorrow` date header and `@time` tags):
    ```text
    tomorrow
    CHEM
    LECTURE - 2 lec @morning
    QUESTION - DPP 5 @till-6
    ```

---

### 2️⃣ Multi-User & Group Study Topics (`/set`)

* **One-Click Topic Linking (`/set`)**:
  * Any user can link their daily targets to any group or forum topic by adding the bot to the group and sending `/set` inside their preferred topic.
  * **Shared Topic Support**: 3–10+ study buddies can run `/set` in the **same group topic**. Each student gets their own clean, separate checklist message in that topic.
* **Clean Clickable Name Headers**:
  * Instead of long text with `@usernames`, checklist headers display a clean clickable link to the user's profile:
    > 🎯 **<a href="#">Anurag</a>'s Targets • `2026-10-04`**
  * Works perfectly even if users do not have a Telegram `@username` configured.
* **Click Authorization (Anti-Trolling)**:
  * Only the owner of the checklist can tap its buttons. If another group member taps a button on someone else's checklist, the bot displays a friendly alert:
    > *"⚠️ This is not your checklist! You can only mark your own targets."*
* **Group Motivation & Celebrations 🔥**:
  * When a user clicks **`🏁 Finish Day`**, the bot posts a celebration shoutout in the linked topic:
    > *"🎉 **Anurag** just completed today's study targets (5/5 • 100%)! 🔥"*
  * When a user inputs test scores via `[📝 Enter Score]`, the bot announces the achievement in the topic:
    > *"🎊 **Anurag** scored **650/720** on their test! 🚀"*

---

### 3️⃣ Interactive Checklist & Real-Time Dual Sync

* **Dual-Sync Mirroring**: Checklist is published to both the user's private DM and their linked group topic. Tapping a task in either location updates both messages instantly.
* **In-Place Updates**: Adding more targets later in the day automatically updates today's existing checklist messages without creating duplicate spam in the group topic.
* **Question Tracking**: Incremental or absolute question logging (e.g. `50` sets `50/81`, while `+10` adds 10 more). Tapping questions sends progress prompt to DM and group, allows entering question number in DM, and broadcasts question completion updates to the group topic.
* **Target Management & Deletion (`/delete`)**: Interactive menu allowing users to delete specific individual targets or all targets for today, tomorrow, or any custom date.
* **Test Score Recording**: Tap `[📝 Enter Score]` to input exam/mock test results (e.g., `620/720`) with instant synchronization.
* **🔒 48-Hour Lock Rule**: Targets older than 48 hours are permanently locked and cannot be retroactively modified, keeping past records authentic and compacting storage.

---

### 4️⃣ Peer Summary & Progress Reports (`/summary`)

* **In Groups:** Reply to any friend's message with `/summary` to view their 5-day study streak, question totals, and completion percentage!
* **In Private DM:** Type `/summary` to see your own recent study metrics card.

---

### 5️⃣ Standalone Interactive HTML Report (`/export`)

* Type `/export` in DM to receive a **self-contained `.html` file** of your 30-day study history.
* **Features:**
  * 🌙 **Auto Dark / Light Theme** (adapts to browser/device mode + manual ☀️/🌙 toggle).
  * ⚡ **Sticky Subject Filter Pills**: Tap *Physics*, *Chemistry*, *Biology*, or *Tests* to instantly filter your view without page reloads or back buttons.
  * 📊 **Dynamic KPI Stat Cards**: Automatically recalculates metrics for the active subject filter.
  * 📂 **Detailed Chapter Breakdowns**: Displays full task lists, question progress bars (`50/81`), and test score badges.
  * 📴 **100% Offline**: Zero external CSS, fonts, or CDNs required. Opens in any browser on iPhone, Android, or PC.
  * 🖨️ **Print to PDF**: Press `Ctrl + P` to export a clean A4 study report.

---

### 6️⃣ Telegram-as-a-Database (Zero External DB)

* **No Postgres/MySQL/Redis needed**: Each user's persistent state is serialized as JSON and stored inside a pinned state message in their private DM with the bot.
* **Safety Banner**: The pinned message includes a clear warning banner:
  ```text
  📌 Daily Target Tracker Storage
  ⚠️ DO NOT DELETE OR UNPIN THIS MESSAGE!
  This message securely stores your study streaks, targets, and test scores.
  ```
* **Unlimited Scalability**: Because each user gets their own pinned message, there is zero database contention and no shared message character limit.

---

### 7️⃣ Render & Cloud Ready

* Built-in lightweight `aiohttp` server listening on `$PORT`.
* Health endpoints: `GET /` and `GET /health` returning `200 OK` for continuous uptime monitoring on Render, Railway, or Fly.io.

---

## 📌 Usage Commands Summary

| Command / Input | Scope | Description |
| :--- | :---: | :--- |
| `/start` | Private DM | Clean welcome message & launch button for WebApp |
| `/help` | Both | Interactive button-based help center |
| `/target <syntax>` | Private DM | Quick command parsing (e.g. `/target phy L2 Q50 ncert`) |
| `/q <syntax>` | Private DM | Alias for `/target` |
| `/summary` | Both | Shows 5-day study progress (reply to a friend in groups) |
| `/export` | Private DM | Generates and sends your standalone interactive HTML dashboard |
| `/set` | Group / Topic | Links the specific group forum topic to your account |
| `/set` | Private DM | Displays current linked topic status and instructions |
| `/delete [date]` | Private DM | Interactive menu to delete specific individual targets or all targets |
| Direct Multiline Text | Private DM | Parses raw subject and study target blocks |
| WebApp Button | Private DM | Opens visual builder for multi-target entry |

---

## 📄 License
This project is open-source under the [MIT License](LICENSE).
