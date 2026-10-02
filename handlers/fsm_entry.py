"""Guided, step-by-step target creation via aiogram FSM (the /new flow)."""

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

router = Router()

SUBJECTS = ["Physics", "Chemistry", "Botany", "Zoology"]
TASK_TYPES = ["Lecture", "Notes-making", "Revision", "NCERT read"]


class NewTarget(StatesGroup):
    subject = State()
    custom_subject = State()
    chapter = State()
    task_type = State()
    custom_type = State()
    lecture_count = State()
    notes = State()
    test_name = State()


def subject_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=s, callback_data=f"subj|{s}")] for s in SUBJECTS]
    rows.append([
        InlineKeyboardButton(text="📝 TEST", callback_data="subj|TEST"),
        InlineKeyboardButton(text="✏️ Custom", callback_data="subj|CUSTOM"),
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def type_kb() -> InlineKeyboardMarkup:
    rows = [[InlineKeyboardButton(text=t, callback_data="type|" + t)] for t in TASK_TYPES]
    rows.append([InlineKeyboardButton(text="✏️ Custom", callback_data="type|CUSTOM")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def add_more_kb() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="➕ Add another task", callback_data="more|yes"),
        InlineKeyboardButton(text="🚀 Publish", callback_data="more|publish"),
    ]])


async def finish(m: Message, state: FSMContext, storage: TelegramStorage) -> None:
    data = await state.get_data()
    specs: list = data.get("specs", [])
    if not specs:
        await m.answer("Nothing to publish — add at least one task. Use /new to start again.")
        await state.clear()
        return
    date = today_str()
    await storage.add_tasks(date, specs)
    await storage.publish_pair(date, data["owner_id"])
    await state.clear()
    await m.answer("✅ Target list published to your DM and the group topic!")


# --------------------------------------------------------------------------- #
#  Entry points
# --------------------------------------------------------------------------- #
@router.message(Command("start"), F.chat.type == "private")
async def cmd_start(m: Message):
    await m.answer(
        "👋 <b>Daily Target Tracker</b>\n\n"
        "• /new — add targets step by step\n"
        "• Send a photo of handwritten targets and I'll import them automatically\n"
        "• /today — show today's progress"
    )


@router.message(Command("today"), F.chat.type == "private")
async def cmd_today(m: Message, storage: TelegramStorage):
    state = await storage.load()
    day = state.get("dates", {}).get(today_str())
    if not day or not day["tasks"]:
        return await m.answer("No targets set for today yet. Use /new or send a photo! 🙂")
    await m.answer(render_text(today_str(), day["tasks"]))


@router.message(Command("new"), F.chat.type == "private")
async def cmd_new(m: Message, state: FSMContext):
    await state.set_state(NewTarget.subject)
    await state.update_data(specs=[], owner_id=m.from_user.id)
    await m.answer("Step 1️⃣ — Choose the subject:", reply_markup=subject_kb())


# --------------------------------------------------------------------------- #
#  Step 1: subject
# --------------------------------------------------------------------------- #
@router.callback_query(NewTarget.subject, F.data.startswith("subj|"))
async def pick_subject(cb: CallbackQuery, state: FSMContext):
    choice = cb.data.split("|", 1)[1]
    await cb.answer()
    if choice == "CUSTOM":
        await state.set_state(NewTarget.custom_subject)
        return await cb.message.answer("Type the custom subject name:")
    if choice == "TEST":
        await state.set_state(NewTarget.test_name)
        return await cb.message.answer("What's the name of the test? (e.g. NEET Mock #12)")
    await state.update_data(subject=choice)
    await state.set_state(NewTarget.chapter)
    await cb.message.answer(f"Step 2️⃣ — Chapter name for <b>{choice}</b>:")


@router.message(NewTarget.custom_subject, F.text)
async def custom_subject(m: Message, state: FSMContext):
    await state.update_data(subject=m.text.strip())
    await state.set_state(NewTarget.chapter)
    await m.answer(f"Step 2️⃣ — Chapter name for <b>{m.text.strip()}</b>:")


# TEST: name -> create score task, skip straight to dispatch
@router.message(NewTarget.test_name, F.text)
async def test_name(m: Message, state: FSMContext, storage: TelegramStorage):
    name = m.text.strip()
    data = await state.get_data()
    specs = data.get("specs", [])
    specs.append({"label": f"TEST — {name}", "kind": "score"})
    await state.update_data(specs=specs)
    await finish(m, state, storage)


# --------------------------------------------------------------------------- #
#  Step 2: chapter
# --------------------------------------------------------------------------- #
@router.message(NewTarget.chapter, F.text)
async def chapter(m: Message, state: FSMContext):
    await state.update_data(chapter=m.text.strip())
    await state.set_state(NewTarget.task_type)
    await m.answer("Step 3️⃣ — Task type:", reply_markup=type_kb())


# --------------------------------------------------------------------------- #
#  Step 3: task type
# --------------------------------------------------------------------------- #
@router.callback_query(NewTarget.task_type, F.data.startswith("type|"))
async def pick_type(cb: CallbackQuery, state: FSMContext):
    choice = cb.data.split("|", 1)[1]
    await cb.answer()
    if choice == "CUSTOM":
        await state.set_state(NewTarget.custom_type)
        return await cb.message.answer("Type the custom task type:")
    await state.update_data(task_type=choice)
    if choice == "Lecture":
        await state.set_state(NewTarget.lecture_count)
        return await cb.message.answer("How many lectures? (send a number, e.g. 3)")
    await state.set_state(NewTarget.notes)
    await cb.message.answer("Optional note for this task (or send /skip):")


@router.message(NewTarget.custom_type, F.text)
async def custom_type(m: Message, state: FSMContext):
    await state.update_data(task_type=m.text.strip())
    await state.set_state(NewTarget.notes)
    await m.answer("Optional note for this task (or send /skip):")


# --------------------------------------------------------------------------- #
#  Step 4: dynamic lecture splitting + optional note
# --------------------------------------------------------------------------- #
@router.message(NewTarget.lecture_count, F.text)
async def lecture_count(m: Message, state: FSMContext):
    try:
        count = int(m.text.strip())
        if not 1 <= count <= 50:
            raise ValueError
    except ValueError:
        return await m.answer("Please send a whole number between 1 and 50.")
    await state.update_data(lecture_count=count)
    await state.set_state(NewTarget.notes)
    await m.answer("Optional note for this task (or send /skip):")


@router.message(NewTarget.notes)
async def notes(m: Message, state: FSMContext):
    note = "" if (m.text or "").strip().lower() in ("/skip", "skip") else (m.text or "").strip()
    data = await state.get_data()
    subject, chapter, ttype = data["subject"], data["chapter"], data.get("task_type", "Task")
    specs = data.get("specs", [])

    def label(kind_word: str, idx: int = None) -> str:
        base = f"{kind_word} {idx} — {chapter} ({subject})" if idx else f"{kind_word} — {chapter} ({subject})"
        return f"{base} · {note}" if note else base

    if ttype == "Lecture" and data.get("lecture_count", 1) > 1:
        specs += [{"label": label("Lecture", i)} for i in range(1, data["lecture_count"] + 1)]
    else:
        specs.append({"label": label(ttype)})
    await state.update_data(specs=specs)

    await state.set_state(NewTarget.subject)  # next decision: add more or publish
    await m.answer(
        f"Saved! You have <b>{len(specs)}</b> task(s) queued.",
        reply_markup=add_more_kb(),
    )


@router.callback_query(F.data == "more|yes")
async def add_more(cb: CallbackQuery, state: FSMContext):
    await cb.answer()
    await state.set_state(NewTarget.subject)
    await cb.message.answer("Step 1️⃣ — Choose the subject:", reply_markup=subject_kb())


@router.callback_query(F.data == "more|publish")
async def publish(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    await cb.answer()
    await finish(cb.message, state, storage)
