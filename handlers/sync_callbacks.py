"""Callbacks: ticking tasks, dual-sync edits, click authorization, and test score entry."""

import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

import config
from storage import TelegramStorage

router = Router()


class ScoreInput(StatesGroup):
    waiting = State()


class QuestionInput(StatesGroup):
    waiting = State()


# --------------------------------------------------------------------------- #
#  Toggling tasks (dual-sync + authorization)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Already recorded 🎉")


@router.callback_query(F.data.startswith("tg|"))
async def toggle(cb: CallbackQuery, storage: TelegramStorage):
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]
    pair_index = int(parts[3])
    task_id = parts[4]

    # Authorization check
    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ This is not your checklist! You can only mark your own targets.", show_alert=True)

    await cb.answer()
    done = await storage.toggle_task(owner_id, date, pair_index, task_id)
    if done:
        await cb.answer("Done! 💪")


# --------------------------------------------------------------------------- #
#  Question entry flow (dual-sync + authorization)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("qs|"))
async def questions_prompt(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]
    pair_index = int(parts[3])
    task_id = parts[4]

    # Authorization check
    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ This is not your checklist! You can only log questions on your own targets.", show_alert=True)

    store_state = await storage.load(owner_id)
    task = store_state.get("dates", {}).get(date, {}).get("tasks", {}).get(task_id, {})
    if task.get("done"):
        return await cb.answer("Already completed! 🎉")

    await state.set_state(QuestionInput.waiting)
    await state.update_data(owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id)
    await cb.answer()

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            f"✍️ How many more questions did you solve? (Total: {task.get('total_q', 0)})",
        )
    except Exception:
        await cb.answer(
            "Open a DM with me first, then tap the button again.",
            show_alert=True,
        )


@router.message(QuestionInput.waiting, F.text.regexp(r"^\d+$"))
async def questions_received(m: Message, state: FSMContext, storage: TelegramStorage):
    solved = int(m.text.strip())
    data = await state.get_data()
    await state.clear()

    owner_id = data["owner_id"]
    date = data["date"]
    pair_index = data["pair_index"]
    task_id = data["task_id"]

    store_state = await storage.load(owner_id)
    task = store_state.get("dates", {}).get(date, {}).get("tasks", {}).get(task_id, {})
    new_solved = task.get("solved_q", 0) + solved

    done = await storage.set_questions_solved(owner_id, date, pair_index, task_id, new_solved)
    if done:
        await m.answer("🎉 Target completed!")
    else:
        await m.answer(f"📝 Progress recorded: {new_solved}/{task.get('total_q', 0)} questions")


@router.message(QuestionInput.waiting)
async def questions_invalid(m: Message):
    await m.answer("Please send a valid number.")


# --------------------------------------------------------------------------- #
#  Finish Day (dual-sync + authorization + group celebration)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("finish|"))
async def finish_day(cb: CallbackQuery, storage: TelegramStorage):
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]
    pair_index = int(parts[3])

    # Authorization check
    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ This is not your checklist! You can only finish your own day's targets.", show_alert=True)

    await cb.answer()

    state = await storage.load(owner_id)
    day = state.get("dates", {}).get(date)
    if not day or not day.get("tasks"):
        return await cb.answer("No targets found for today.")

    tasks = day["tasks"]
    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks.values() if t.get("done"))
    percentage = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0

    # Disable buttons in both DM and topic
    await storage.finish_pair(owner_id, date, pair_index)

    user_name = state.get("user_name") or cb.from_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={owner_id}\">{escaped_name}</a>"

    # Send celebration to user's linked topic if configured
    cfg = state.get("config", {})
    group_id = cfg.get("group_chat_id") or config.GROUP_CHAT_ID
    topic_id = cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

    if group_id and topic_id:
        try:
            await cb.bot.send_message(
                group_id,
                f"🎉 {user_link} just completed today's study targets ({done_tasks}/{total_tasks} • {percentage}%)! 🔥",
                message_thread_id=topic_id,
            )
        except Exception:
            pass

    await cb.message.answer(f"🏁 Day finished! You completed {done_tasks}/{total_tasks} ({percentage}%) targets.")


# --------------------------------------------------------------------------- #
#  Score entry flow (dual-sync + authorization)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("sc|"))
async def score_prompt(cb: CallbackQuery, state: FSMContext):
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]
    pair_index = int(parts[3])
    task_id = parts[4]

    # Authorization check
    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ This is not your checklist! You can only enter your own scores.", show_alert=True)

    await state.set_state(ScoreInput.waiting)
    await state.update_data(owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id)
    await cb.answer()

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            "✍️ Send your score in the format <b>610/720</b>:",
        )
    except Exception:
        await cb.answer(
            "Open a DM with me first (press /start), then tap the button again.",
            show_alert=True,
        )


@router.message(ScoreInput.waiting, F.text.regexp(r"^\s*\d{1,4}\s*/\s*\d{1,4}\s*$"))
async def score_received(m: Message, state: FSMContext, storage: TelegramStorage):
    score = m.text.replace(" ", "")
    data = await state.get_data()
    await state.clear()

    owner_id = data["owner_id"]
    date = data["date"]
    pair_index = data["pair_index"]
    task_id = data["task_id"]

    await storage.set_score(owner_id, date, pair_index, task_id, score)
    await m.answer(f"🎉 Score recorded: <b>{score}</b>")

    state_data = await storage.load(owner_id)
    user_name = state_data.get("user_name") or m.from_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={owner_id}\">{escaped_name}</a>"

    cfg = state_data.get("config", {})
    group_id = cfg.get("group_chat_id") or config.GROUP_CHAT_ID
    topic_id = cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

    if group_id and topic_id:
        try:
            await m.bot.send_message(
                group_id,
                f"🎊 {user_link} scored <b>{score}</b> on their test! 🚀",
                message_thread_id=topic_id,
            )
        except Exception:
            pass


@router.message(ScoreInput.waiting)
async def score_invalid(m: Message):
    await m.answer("That doesn't look like a score. Send it as <b>610/720</b>:")


# --------------------------------------------------------------------------- #
#  Deletion functionality (per-user)
# --------------------------------------------------------------------------- #
@router.message(Command("delete"), F.chat.type == "private")
async def cmd_delete_date(m: Message, storage: TelegramStorage):
    """Delete all targets for a specific date from user's state."""
    from storage import today_str
    text = m.text.strip()
    args = text.split()
    user_id = m.from_user.id

    if len(args) > 1:
        date = args[1]
    else:
        date = today_str()

    state = await storage.load(user_id)
    day = state.get("dates", {}).get(date)

    if not day or not day.get("tasks"):
        return await m.answer(f"❌ No targets found for <code>{date}</code>")

    from storage import render_text
    text_content = render_text(date, day["tasks"], user_id=user_id, user_name=m.from_user.full_name, title="🗑️ Delete these targets?")

    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes, Delete All", callback_data=f"deldate_confirm|{user_id}|{date}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="deldate_cancel"),
    ]])

    await m.answer(text_content, reply_markup=kb)


@router.callback_query(F.data.startswith("deldate_confirm|"))
async def confirm_delete_date(cb: CallbackQuery, storage: TelegramStorage):
    """Confirm and execute deletion of entire date."""
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]

    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ You can only delete your own targets.", show_alert=True)

    await cb.answer()
    success = await storage.delete_date(owner_id, date)

    if success:
        await cb.message.edit_text(f"✅ All targets for <code>{date}</code> have been deleted!")
    else:
        await cb.message.edit_text("❌ Failed to delete targets")


@router.callback_query(F.data == "deldate_cancel")
async def cancel_delete(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("❌ Deletion cancelled")