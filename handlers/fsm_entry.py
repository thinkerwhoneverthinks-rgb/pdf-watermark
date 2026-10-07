import datetime
import html
import json
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import config
from report_generator import generate_html_report
from storage import TelegramStorage, render_text, today_str, tomorrow_str

router = Router()


class TargetFSM(StatesGroup):
    subject = State()
    task = State()
    count = State()
    custom_task = State()


# --------------------------------------------------------------------------- #
#  Help / Start Commands
# --------------------------------------------------------------------------- #
@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(m: Message, storage: TelegramStorage):
    # Save user display name into state
    user_id = m.from_user.id
    user_name = m.from_user.full_name
    state = await storage.load(user_id)
    state["user_name"] = user_name
    await storage.save(user_id, state)

    welcome_text = (
        f"👋 <b>Welcome {html.escape(m.from_user.first_name)}!</b>\n\n"
        "Track your daily study targets, practice questions, and mock tests with real-time group sync.\n\n"
        "Tap below to begin planning today or tomorrow's targets:"
    )

    kb = None
    if config.WEBAPP_URL:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="🚀 Open Web App", web_app=WebAppInfo(url=config.WEBAPP_URL))]],
            resize_keyboard=True
        )
    await m.answer(welcome_text, reply_markup=kb)


@router.message(Command("help"))
async def cmd_help(m: Message):
    from handlers.sync_callbacks import get_main_help_keyboard
    help_text = (
        "📖 <b>Daily Target Tracker — Help Center</b>\n\n"
        "Tap a topic below to view instructions:"
    )
    await m.answer(help_text, reply_markup=get_main_help_keyboard())


# --------------------------------------------------------------------------- #
#  Export Standalone HTML Dashboard Report (/export, /report)
# --------------------------------------------------------------------------- #
@router.message(Command("export", "report"), F.chat.type == "private")
async def cmd_export_report(m: Message, storage: TelegramStorage):
    user_id = m.from_user.id
    user_name = m.from_user.full_name
    state = await storage.load(user_id)
    dates_data = state.get("dates", {})

    if not dates_data:
        return await m.answer("ℹ️ No study history recorded yet! Add some targets first using the Web App or <code>/target</code>.")

    wait_msg = await m.answer("⏳ Generating your interactive study report...")

    try:
        html_content = generate_html_report(user_id, user_name, dates_data)
        html_bytes = html_content.encode("utf-8")

        date_today = today_str()
        safe_name = re.sub(r"[^\w\-]", "_", user_name).strip("_")
        filename = f"Study_Report_{safe_name}_{date_today}.html"

        doc = BufferedInputFile(html_bytes, filename=filename)

        caption = (
            f"📊 <b>Study Dashboard Report ({len(dates_data)} Days Recorded)</b>\n\n"
            "✨ <b>Features:</b>\n"
            "• 🌙 <b>Auto Dark / Light Theme</b> + manual switcher\n"
            "• ⚡ <b>Clickable Subject Filter Tabs</b> (Physics, Chem, Bio, Tests)\n"
            "• 📈 <b>Live Question Progress</b>, Time Slots & Chapter Breakdowns\n\n"
            "<i>Open this HTML file in Chrome, Safari, or any browser on your phone or PC.</i>"
        )

        await m.answer_document(doc, caption=caption)
        await wait_msg.delete()
    except Exception as e:
        await wait_msg.edit_text(f"❌ Failed to generate report: {e}")


# --------------------------------------------------------------------------- #
#  Group / Topic Binding (/set)
# --------------------------------------------------------------------------- #
@router.message(Command("set"))
async def cmd_set(m: Message, storage: TelegramStorage):
    user_id = m.from_user.id
    user_name = m.from_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={user_id}\">{escaped_name}</a>"

    if m.chat.type in ("group", "supergroup"):
        group_id = m.chat.id
        topic_id = m.message_thread_id or 0

        # Load and update user's configuration
        state = await storage.load(user_id)
        state["user_name"] = user_name
        state.setdefault("config", {})
        state["config"]["group_chat_id"] = group_id
        state["config"]["topic_thread_id"] = topic_id

        try:
            await storage.save(user_id, state)
            topic_info = f" (Topic ID: <code>{topic_id}</code>)" if topic_id else ""
            await m.reply(
                f"✅ <b>Linked!</b> {user_link}'s daily targets will now automatically be posted to this topic{topic_info}."
            )
        except Exception:
            bot_info = await m.bot.get_me()
            await m.reply(
                f"⚠️ {user_link}, please start me in private DM first (@{bot_info.username}) so I can initialize your checklist, then type <code>/set</code> here again!"
            )
    else:
        # Ran inside private DM
        state = await storage.load(user_id)
        current_cfg = state.get("config", {})
        gid = current_cfg.get("group_chat_id") or config.GROUP_CHAT_ID
        tid = current_cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

        if gid and tid:
            status_text = f"📍 <b>Currently Linked Topic:</b> Group <code>{gid}</code>, Topic <code>#{tid}</code>\n\n"
        elif gid:
            status_text = f"📍 <b>Currently Linked Group:</b> Group <code>{gid}</code>\n\n"
        else:
            status_text = "📍 <b>Currently Linked Topic:</b> None (targets appear in DM only)\n\n"

        await m.answer(
            f"ℹ️ {status_text}"
            "<b>How to link a group forum topic:</b>\n"
            "1. Add this bot to your study group.\n"
            "2. Open the specific forum topic where you want targets sent.\n"
            "3. Send <code>/set</code> inside that topic!\n\n"
            "Multiple group members can send <code>/set</code> in the same topic to track targets together."
        )


# --------------------------------------------------------------------------- #
#  Method 1: Web App Data Handler (Supports Date & Time Slots)
# --------------------------------------------------------------------------- #
@router.message(F.web_app_data, F.chat.type == "private")
async def handle_webapp_data(m: Message, storage: TelegramStorage):
    try:
        raw_payload = json.loads(m.web_app_data.data)

        # Handle both {date: "...", tasks: [...]} and legacy flat array [...]
        if isinstance(raw_payload, dict) and "tasks" in raw_payload:
            target_date = raw_payload.get("date") or today_str()
            data_list = raw_payload.get("tasks", [])
        elif isinstance(raw_payload, list):
            target_date = today_str()
            data_list = raw_payload
        else:
            target_date = today_str()
            data_list = [raw_payload]

        all_specs = []
        for data in data_list:
            subject = data.get("subject", "General")
            chapter = data.get("chapter", "")
            task_type = data.get("type", "Task")
            count = data.get("count", 1)
            details = data.get("details", "")
            time_slot = data.get("time_slot", "")

            all_specs.extend(_build_specs_from_task(subject, task_type, count, details, chapter, time_slot))

        user_id = m.from_user.id
        user_name = m.from_user.full_name
        await storage.add_tasks(user_id, target_date, all_specs)
        await storage.publish_pair(user_id, target_date, m.chat.id, user_name=user_name)

    except Exception as e:
        await m.answer(f"❌ Failed to process WebApp data: {e}")


# --------------------------------------------------------------------------- #
#  Method 2: Quick Syntax Parsing (/target or /q)
#  Supports:
#  - Date prefix: tomorrow, today, or YYYY-MM-DD
#  - Time tags: @morning, @afternoon, @till-6, @1-6pm, time:1-6
# --------------------------------------------------------------------------- #
@router.message(Command("target", "q"), F.chat.type == "private")
async def cmd_target(m: Message, storage: TelegramStorage):
    text = re.sub(r"^/(target|q)\s*", "", m.text, flags=re.IGNORECASE).strip()
    if not text:
        return await m.answer(
            "Usage:\n"
            "• <code>/target phy L2 Q50 ncert Thermodynamics</code>\n"
            "• <code>/target tomorrow phy L2 @morning Q50 @till-6 Thermodynamics</code>"
        )

    parts = text.split()
    target_date = today_str()

    # Check for date prefix
    if parts:
        first_word = parts[0].lower()
        if first_word == "tomorrow":
            target_date = tomorrow_str()
            parts = parts[1:]
        elif first_word == "today":
            target_date = today_str()
            parts = parts[1:]
        elif re.match(r"^\d{4}-\d{2}-\d{2}$", first_word):
            target_date = first_word
            parts = parts[1:]

    subject = "General"

    # Check for subject
    if parts:
        first = parts[0].lower()
        if first in ["phy", "physics"]:
            subject = "Physics"
            parts = parts[1:]
        elif first in ["chem", "chemistry"]:
            subject = "Chemistry"
            parts = parts[1:]
        elif first in ["bio", "biology"]:
            subject = "Biology"
            parts = parts[1:]
        elif first == "test":
            subject = "Test"
            parts = parts[1:]

    custom_parts = []
    tasks_to_add = []  # list of (type, count, time_slot)
    current_time_slot = ""

    for part in parts:
        # Check time slot tags (@morning, @till-6, @1-6pm, etc.)
        if part.startswith("@") and len(part) > 1:
            current_time_slot = part[1:].replace("-", " ")
        elif part.lower().startswith("time:"):
            current_time_slot = part[5:]
        elif re.match(r"^L\d+$", part, re.IGNORECASE):
            tasks_to_add.append(("Lecture", int(part[1:]), current_time_slot))
        elif re.match(r"^Q\d+$", part, re.IGNORECASE):
            tasks_to_add.append(("Questions", int(part[1:]), current_time_slot))
        elif part.lower() in ["ncert", "rev", "revision", "notes"]:
            ttype = "NCERT" if part.lower() == "ncert" else ("Revision" if part.lower().startswith("rev") else "Short Notes")
            tasks_to_add.append((ttype, 1, current_time_slot))
        else:
            custom_parts.append(part)

    chapter = " ".join(custom_parts) if custom_parts else ""

    specs = []
    for ttype, count, slot in tasks_to_add:
        specs.extend(_build_specs_from_task(subject, ttype, count, "", chapter, slot or current_time_slot))

    # If only custom words were given without specific markers, treat whole thing as custom task
    if not specs and custom_parts:
        specs.extend(_build_specs_from_task(subject, "Custom", 1, chapter, chapter, current_time_slot))

    if not specs:
        return await m.answer("No valid targets found in quick syntax. Example: /target tomorrow phy L2 @morning Q50 @till-6 Thermodynamics")

    user_id = m.from_user.id
    user_name = m.from_user.full_name
    await storage.add_tasks(user_id, target_date, specs)
    await storage.publish_pair(user_id, target_date, m.chat.id, user_name=user_name)


def _build_specs_from_task(subject: str, task_type: str, count: int, details: str, chapter: str = "", time_slot: str = "") -> list:
    specs = []
    display_title = chapter or subject
    if task_type == "Lecture":
        for i in range(1, count + 1):
            specs.append({
                "label": f"Lecture {i} ({display_title})",
                "kind": "task",
                "time_slot": time_slot,
            })
    elif task_type == "Questions":
        specs.append({
            "label": f"Questions ({display_title})",
            "kind": "questions",
            "total_q": count,
            "solved_q": 0,
            "time_slot": time_slot,
        })
    elif task_type == "Custom":
        label_text = details if details else display_title
        specs.append({
            "label": f"{label_text} ({subject})" if details and subject != "General" else label_text,
            "kind": "task",
            "time_slot": time_slot,
        })
    else:
        specs.append({
            "label": f"{task_type} ({display_title})",
            "kind": "task",
            "time_slot": time_slot,
        })
    return specs
