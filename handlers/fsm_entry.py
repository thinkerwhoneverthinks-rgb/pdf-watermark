import html
import json
import re

from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    WebAppInfo,
)

import config
from storage import TelegramStorage, render_text, today_str

router = Router()


class TargetFSM(StatesGroup):
    subject = State()
    task = State()
    count = State()
    custom_task = State()


# --------------------------------------------------------------------------- #
#  Help / Start Command
# --------------------------------------------------------------------------- #
@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(m: Message):
    help_text = (
        "🤖 <b>Welcome to your Daily Target Bot!</b>\n\n"
        "Here are the ways to use the bot:\n\n"
        "<b>1️⃣ Web App UI (Recommended):</b>\n"
        "Click the 'Open Web App' button below to visually stage and send multiple targets at once.\n\n"
        "<b>2️⃣ Quick Syntax (/target or /q):</b>\n"
        "Send: <code>/target phy L2 Q50 ncert Thermodynamics</code>\n\n"
        "<b>3️⃣ Direct Text:</b>\n"
        "Send your targets in plain text like:\n"
        "<i>CHEM\nLECTURE - 2 lec\nQUESTION - DPP 5</i>\n\n"
        "<b>4️⃣ Group Topic Sync (/set):</b>\n"
        "Add me to your study group and send <code>/set</code> inside your specific topic! "
        "Multiple students can send <code>/set</code> in the same topic to track targets together."
    )

    kb = None
    if config.WEBAPP_URL:
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Open Web App", web_app=WebAppInfo(url=config.WEBAPP_URL))]],
            resize_keyboard=True
        )
    await m.answer(help_text, reply_markup=kb)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(m: Message, storage: TelegramStorage):
    # Initialize user state and save display name
    user_id = m.from_user.id
    user_name = m.from_user.full_name
    state = await storage.load(user_id)
    state["user_name"] = user_name
    await storage.save(user_id, state)
    await cmd_help(m)


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
#  Method 1: Web App Data Handler
# --------------------------------------------------------------------------- #
@router.message(F.web_app_data, F.chat.type == "private")
async def handle_webapp_data(m: Message, storage: TelegramStorage):
    try:
        data_list = json.loads(m.web_app_data.data)
        if isinstance(data_list, dict):
            # Fallback for single-object webapp payloads
            data_list = [data_list]

        all_specs = []
        for data in data_list:
            subject = data.get("subject", "General")
            chapter = data.get("chapter", "")
            task_type = data.get("type", "Task")
            count = data.get("count", 1)
            details = data.get("details", "")

            all_specs.extend(_build_specs_from_task(subject, task_type, count, details, chapter))

        user_id = m.from_user.id
        user_name = m.from_user.full_name
        date = today_str()
        await storage.add_tasks(user_id, date, all_specs)
        await storage.publish_pair(user_id, date, m.chat.id, user_name=user_name)

    except Exception as e:
        await m.answer(f"❌ Failed to process WebApp data: {e}")


# --------------------------------------------------------------------------- #
#  Method 2: Quick Syntax Parsing (/target or /q)
# --------------------------------------------------------------------------- #
@router.message(Command("target", "q"), F.chat.type == "private")
async def cmd_target(m: Message, storage: TelegramStorage):
    text = re.sub(r"^/(target|q)\s*", "", m.text, flags=re.IGNORECASE).strip()
    if not text:
        return await m.answer("Usage: /target phy L2 Q50 ncert custom topic\n(or /q phy L2 Q50 ...)")

    parts = text.split()
    subject = "General"

    # Check first part for subject
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
    tasks_to_add = []  # list of (type, count)

    for part in parts:
        if re.match(r"^L\d+$", part, re.IGNORECASE):
            tasks_to_add.append(("Lecture", int(part[1:])))
        elif re.match(r"^Q\d+$", part, re.IGNORECASE):
            tasks_to_add.append(("Questions", int(part[1:])))
        elif part.lower() in ["ncert", "rev", "revision", "notes"]:
            ttype = "NCERT" if part.lower() == "ncert" else ("Revision" if part.lower().startswith("rev") else "Short Notes")
            tasks_to_add.append((ttype, 1))
        else:
            custom_parts.append(part)

    chapter = " ".join(custom_parts) if custom_parts else ""

    specs = []
    for ttype, count in tasks_to_add:
        specs.extend(_build_specs_from_task(subject, ttype, count, "", chapter))

    # If only custom words were given without specific markers, treat whole thing as custom task
    if not specs and custom_parts:
        specs.extend(_build_specs_from_task(subject, "Custom", 1, chapter, chapter))

    if not specs:
        return await m.answer("No valid targets found in quick syntax. Example: /target phy L2 Q50 ncert Thermodynamics")

    user_id = m.from_user.id
    user_name = m.from_user.full_name
    date = today_str()
    await storage.add_tasks(user_id, date, specs)
    await storage.publish_pair(user_id, date, m.chat.id, user_name=user_name)


def _build_specs_from_task(subject: str, task_type: str, count: int, details: str, chapter: str = "") -> list:
    specs = []
    display_title = chapter or subject
    if task_type == "Lecture":
        for i in range(1, count + 1):
            specs.append({
                "label": f"Lecture {i} ({display_title})",
                "kind": "task"
            })
    elif task_type == "Questions":
        specs.append({
            "label": f"Questions ({display_title})",
            "kind": "questions",
            "total_q": count,
            "solved_q": 0
        })
    elif task_type == "Custom":
        label_text = details if details else display_title
        specs.append({
            "label": f"{label_text} ({subject})" if details and subject != "General" else label_text,
            "kind": "task"
        })
    else:
        specs.append({
            "label": f"{task_type} ({display_title})",
            "kind": "task"
        })
    return specs
