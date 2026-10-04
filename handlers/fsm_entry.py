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
    Message,
)

from storage import TelegramStorage, render_text, today_str
import config

router = Router()


class TargetFSM(StatesGroup):
    subject = State()
    task = State()
    count = State()
    custom_task = State()


# --------------------------------------------------------------------------- #
#  Help Command
# --------------------------------------------------------------------------- #
@router.message(Command("help"), F.chat.type == "private")
async def cmd_help(m: Message):
    help_text = (
        "🤖 <b>Welcome to your Daily Target Bot!</b>\n\n"
        "Here are 3 ways to add your targets:\n\n"
        "<b>1️⃣ Web App UI (Recommended):</b>\n"
        "Click the 'Open Web App' button below to use the easy interface.\n\n"
        "<b>2️⃣ Quick Syntax (/target):</b>\n"
        "Send a message like: <code>/target phy L2 Q50 ncert Thermodynamics</code>\n\n"
        "<b>3️⃣ Direct Text:</b>\n"
        "Just send your targets in plain text like:\n"
        "<i>CHEM\nLECTURE - 2 lec\nQUESTION - DPP 5</i>\n"
    )

    if m.chat.type == "private":
        kb = ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Open Web App", web_app=WebAppInfo(url=config.WEBAPP_URL))]],
            resize_keyboard=True
        )
        await m.answer(help_text, reply_markup=kb)
    else:
        await m.answer(help_text)

async def cmd_start(m: Message):
    await cmd_help(m)


# --------------------------------------------------------------------------- #
#  Method 1: Web App Data Handler
# --------------------------------------------------------------------------- #
@router.message(F.web_app_data, F.chat.type == "private")
async def handle_webapp_data(m: Message, storage: TelegramStorage):
    try:
        data_list = json.loads(m.web_app_data.data)
        if isinstance(data_list, dict):
            # Fallback for old cached webapp payloads
            data_list = [data_list]

        all_specs = []
        for data in data_list:
            subject = data.get("subject", "General")
            chapter = data.get("chapter", "")
            task_type = data.get("type", "Task")
            count = data.get("count", 1)
            details = data.get("details", "")

            all_specs.extend(_build_specs_from_task(subject, task_type, count, details, chapter))

        date = today_str()
        await storage.add_tasks(date, all_specs)
        # Assuming publish_pair is updated to refresh the existing checklist for today
        await storage.publish_pair(date, m.chat.id)

    except Exception as e:
        await m.answer(f"❌ Failed to process WebApp data: {e}")


# --------------------------------------------------------------------------- #
#  Method 2: Quick Syntax Parsing (/target)
# --------------------------------------------------------------------------- #
@router.message(Command("target"), F.chat.type == "private")
async def cmd_target(m: Message, storage: TelegramStorage):
    text = m.text.replace("/target", "", 1).strip()
    if not text:
        return await m.answer("Usage: /target phy L2 Q50 ncert custom topic")

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

    specs = []
    custom_parts = []

    tasks_to_add = [] # (type, count)

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

    for ttype, count in tasks_to_add:
        specs.extend(_build_specs_from_task(subject, ttype, count, "", chapter))

    if not specs:
        return await m.answer("No valid targets found in quick syntax.")

    date = today_str()
    await storage.add_tasks(date, specs)
    await storage.publish_pair(date, m.chat.id)


def _build_specs_from_task(subject: str, task_type: str, count: int, details: str, chapter: str = "") -> list:
    specs = []
    if task_type == "Lecture":
        for i in range(1, count + 1):
            specs.append({
                "label": f"Lecture {i} ({chapter or subject})",
                "kind": "task"
            })
    elif task_type == "Questions":
        # Tracks fraction (0/50)
        specs.append({
            "label": f"Questions ({chapter or subject})",
            "kind": "questions",
            "total_q": count,
            "solved_q": 0
        })
    elif task_type == "Custom":
        specs.append({
            "label": f"{details} ({chapter or subject})",
            "kind": "task"
        })
    else:
        specs.append({
            "label": f"{task_type} ({chapter or subject})",
            "kind": "task"
        })
    return specs
