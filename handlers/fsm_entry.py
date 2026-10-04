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
        "📚 <b>Daily Target Tracker Help</b>\n\n"
        "Here are the ways you can set your daily targets:\n\n"
        "<b>1. 🌐 Web App (Easiest)</b>\n"
        "Click the menu button or use the WebApp to quickly add targets via a beautiful UI.\n\n"
        "<b>2. 🤖 Step-by-Step (/target)</b>\n"
        "Type <code>/target</code> and I'll guide you step-by-step through choosing a subject and task.\n\n"
        "<b>3. ⚡ Quick Syntax (/q)</b>\n"
        "Type your targets on a single line! Example:\n"
        "<code>/q phy L2 Q50 ncert Custom Topic Name</code>\n"
        "<i>Rules:</i>\n"
        "- <code>phy/chem/bio/test</code> sets the subject.\n"
        "- <code>L2</code> adds 2 lectures.\n"
        "- <code>Q50</code> tracks 50 questions.\n"
        "- <code>ncert/rev/notes</code> adds standard tasks.\n"
        "- Anything else becomes a custom task.\n\n"
        "<b>🏁 Finish Day</b>\n"
        "Click the <b>Finish Day</b> button when you're done studying to send a summary to the group!"
    )

    # Send with a WebApp button if configured
    if config.WEBAPP_URL:
        from aiogram.types.web_app_info import WebAppInfo
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="📱 Open Web App", web_app=WebAppInfo(url=config.WEBAPP_URL))
        ]])
        await m.answer(help_text, reply_markup=kb)
    else:
        await m.answer(help_text)


@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(m: Message):
    await cmd_help(m)


# --------------------------------------------------------------------------- #
#  Method 1: Web App Data Handler
# --------------------------------------------------------------------------- #
@router.message(F.web_app_data, F.chat.type == "private")
async def handle_webapp_data(m: Message, storage: TelegramStorage):
    try:
        data = json.loads(m.web_app_data.data)
        subject = data.get("subject", "General")
        task_type = data.get("type", "Task")
        count = data.get("count", 1)
        details = data.get("details", "")

        specs = _build_specs_from_task(subject, task_type, count, details)

        date = today_str()
        await storage.add_tasks(date, specs)
        # Assuming publish_pair is updated to refresh the existing checklist for today
        await storage.publish_pair(date, m.chat.id)

    except Exception as e:
        await m.answer(f"❌ Failed to process WebApp data: {e}")


# --------------------------------------------------------------------------- #
#  Method 2: Step-by-Step Menu (/target)
# --------------------------------------------------------------------------- #
@router.message(Command("target"), F.chat.type == "private")
async def cmd_target(m: Message, state: FSMContext):
    await state.set_state(TargetFSM.subject)
    await state.update_data(owner_id=m.from_user.id)

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Physics", callback_data="tsubj|Physics"),
         InlineKeyboardButton(text="Chemistry", callback_data="tsubj|Chemistry")],
        [InlineKeyboardButton(text="Biology", callback_data="tsubj|Biology"),
         InlineKeyboardButton(text="Test", callback_data="tsubj|Test")]
    ])
    await m.answer("Step 1: Choose a Subject", reply_markup=kb)


@router.callback_query(TargetFSM.subject, F.data.startswith("tsubj|"))
async def target_pick_subject(cb: CallbackQuery, state: FSMContext):
    subject = cb.data.split("|")[1]
    await state.update_data(subject=subject)
    await state.set_state(TargetFSM.task)
    await cb.answer()

    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Lecture", callback_data="ttask|Lecture"),
         InlineKeyboardButton(text="Questions", callback_data="ttask|Questions")],
        [InlineKeyboardButton(text="Revision", callback_data="ttask|Revision"),
         InlineKeyboardButton(text="Short Notes", callback_data="ttask|Short Notes")],
        [InlineKeyboardButton(text="NCERT", callback_data="ttask|NCERT"),
         InlineKeyboardButton(text="Custom", callback_data="ttask|Custom")],
        [InlineKeyboardButton(text="✅ Done", callback_data="ttask|Done")]
    ])
    await cb.message.answer(f"Subject: <b>{subject}</b>\nStep 2: Choose a Task", reply_markup=kb)


@router.callback_query(TargetFSM.task, F.data.startswith("ttask|"))
async def target_pick_task(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    task = cb.data.split("|")[1]
    await cb.answer()

    if task == "Done":
        date = today_str()
        data = await state.get_data()
        await state.clear()
        # Generate the interactive checklist
        await storage.publish_pair(date, cb.message.chat.id)
        return

    await state.update_data(task_type=task)

    if task in ["Lecture", "Questions"]:
        await state.set_state(TargetFSM.count)
        await cb.message.answer(f"How many {task}?")
    elif task == "Custom":
        await state.set_state(TargetFSM.custom_task)
        await cb.message.answer("Type your custom task details:")
    else:
        # Save standard task instantly and return to task selection
        data = await state.get_data()
        specs = _build_specs_from_task(data["subject"], task, 1, "")
        await storage.add_tasks(today_str(), specs)

        # Go back to task selection
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="Lecture", callback_data="ttask|Lecture"),
             InlineKeyboardButton(text="Questions", callback_data="ttask|Questions")],
            [InlineKeyboardButton(text="Revision", callback_data="ttask|Revision"),
             InlineKeyboardButton(text="Short Notes", callback_data="ttask|Short Notes")],
            [InlineKeyboardButton(text="NCERT", callback_data="ttask|NCERT"),
             InlineKeyboardButton(text="Custom", callback_data="ttask|Custom")],
            [InlineKeyboardButton(text="✅ Done", callback_data="ttask|Done")]
        ])
        await cb.message.answer(f"Added {task}!\nAdd another task or click Done:", reply_markup=kb)


@router.message(TargetFSM.count, F.text)
async def target_task_count(m: Message, state: FSMContext, storage: TelegramStorage):
    try:
        count = int(m.text.strip())
        if count <= 0:
            raise ValueError
    except ValueError:
        return await m.answer("Please send a valid number.")

    data = await state.get_data()
    specs = _build_specs_from_task(data["subject"], data["task_type"], count, "")
    await storage.add_tasks(today_str(), specs)

    await state.set_state(TargetFSM.task)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Lecture", callback_data="ttask|Lecture"),
         InlineKeyboardButton(text="Questions", callback_data="ttask|Questions")],
        [InlineKeyboardButton(text="Revision", callback_data="ttask|Revision"),
         InlineKeyboardButton(text="Short Notes", callback_data="ttask|Short Notes")],
        [InlineKeyboardButton(text="NCERT", callback_data="ttask|NCERT"),
         InlineKeyboardButton(text="Custom", callback_data="ttask|Custom")],
        [InlineKeyboardButton(text="✅ Done", callback_data="ttask|Done")]
    ])
    await m.answer(f"Added {count} {data['task_type']}!\nAdd another task or click Done:", reply_markup=kb)


@router.message(TargetFSM.custom_task, F.text)
async def target_custom_task(m: Message, state: FSMContext, storage: TelegramStorage):
    data = await state.get_data()
    specs = _build_specs_from_task(data["subject"], "Custom", 1, m.text.strip())
    await storage.add_tasks(today_str(), specs)

    await state.set_state(TargetFSM.task)
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Lecture", callback_data="ttask|Lecture"),
         InlineKeyboardButton(text="Questions", callback_data="ttask|Questions")],
        [InlineKeyboardButton(text="Revision", callback_data="ttask|Revision"),
         InlineKeyboardButton(text="Short Notes", callback_data="ttask|Short Notes")],
        [InlineKeyboardButton(text="NCERT", callback_data="ttask|NCERT"),
         InlineKeyboardButton(text="Custom", callback_data="ttask|Custom")],
        [InlineKeyboardButton(text="✅ Done", callback_data="ttask|Done")]
    ])
    await m.answer(f"Added custom task!\nAdd another task or click Done:", reply_markup=kb)


# --------------------------------------------------------------------------- #
#  Method 3: Quick Syntax Parsing (/q)
# --------------------------------------------------------------------------- #
@router.message(Command("q"), F.chat.type == "private")
async def cmd_quick_parse(m: Message, storage: TelegramStorage):
    text = m.text.replace("/q", "", 1).strip()
    if not text:
        return await m.answer("Usage: /q phy L2 Q50 ncert custom topic")

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

    for part in parts:
        if re.match(r"^L\d+$", part, re.IGNORECASE):
            count = int(part[1:])
            specs.extend(_build_specs_from_task(subject, "Lecture", count, ""))
        elif re.match(r"^Q\d+$", part, re.IGNORECASE):
            count = int(part[1:])
            specs.extend(_build_specs_from_task(subject, "Questions", count, ""))
        elif part.lower() in ["ncert", "rev", "revision", "notes"]:
            ttype = "NCERT" if part.lower() == "ncert" else ("Revision" if part.lower().startswith("rev") else "Short Notes")
            specs.extend(_build_specs_from_task(subject, ttype, 1, ""))
        else:
            custom_parts.append(part)

    if custom_parts:
        specs.extend(_build_specs_from_task(subject, "Custom", 1, " ".join(custom_parts)))

    if not specs:
        return await m.answer("No valid targets found in quick syntax.")

    date = today_str()
    await storage.add_tasks(date, specs)
    await storage.publish_pair(date, m.chat.id)


def _build_specs_from_task(subject: str, task_type: str, count: int, details: str) -> list:
    specs = []
    if task_type == "Lecture":
        for i in range(1, count + 1):
            specs.append({
                "label": f"Lecture {i} ({subject})",
                "kind": "task"
            })
    elif task_type == "Questions":
        # Tracks fraction (0/50)
        specs.append({
            "label": f"Questions ({subject})",
            "kind": "questions",
            "total_q": count,
            "solved_q": 0
        })
    elif task_type == "Custom":
        specs.append({
            "label": f"{details} ({subject})",
            "kind": "task"
        })
    else:
        specs.append({
            "label": f"{task_type} ({subject})",
            "kind": "task"
        })
    return specs
