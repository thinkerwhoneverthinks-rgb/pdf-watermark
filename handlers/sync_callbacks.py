"""Callbacks: ticking tasks, dual-sync edits, click authorization, 48h locks, /summary, and interactive help."""

import datetime
import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

import config
from storage import TelegramStorage, is_date_locked

router = Router()


class ScoreInput(StatesGroup):
    waiting = State()

class QuestionInput(StatesGroup):
    waiting = State()


# --------------------------------------------------------------------------- #
#  Toggling tasks (dual-sync + authorization + 48h lock)
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

    # 48-Hour lock check
    if is_date_locked(date):
        return await cb.answer("🔒 Locked: Targets older than 48 hours are finalized and cannot be edited.", show_alert=True)

    await cb.answer()
    done = await storage.toggle_task(owner_id, date, pair_index, task_id)
    if done:
        await cb.answer("Done! 💪")


# --------------------------------------------------------------------------- #
#  Question entry flow
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("qs|"))
async def questions_prompt(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    _, date, pair_index, task_id = cb.data.split("|")

    # Check if already done
    store_state = await storage.load()
    task = store_state["dates"][date]["tasks"][task_id]
    if task.get("done"):
        return await cb.answer("Already completed! 🎉")

    await state.set_state(QuestionInput.waiting)
    await state.update_data(date=date, pair_index=int(pair_index), task_id=task_id)
    await cb.answer()

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            f"✍️ How many more questions did you solve? (Total: {task.get('total_q')})",
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

    # Need to add to existing solved amount
    store_state = await storage.load()
    task = store_state["dates"][data["date"]]["tasks"][data["task_id"]]
    new_solved = task.get("solved_q", 0) + solved

    done = await storage.set_questions_solved(data["date"], data["pair_index"], data["task_id"], new_solved)
    if done:
        await m.answer(f"🎉 Questions completed!")
    else:
        await m.answer(f"📝 Progress recorded: {new_solved}/{task.get('total_q')} questions")


@router.message(QuestionInput.waiting)
async def questions_invalid(m: Message):
    await m.answer("Please send a valid number.")


# --------------------------------------------------------------------------- #
#  Finish Day
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("finish|"))
async def finish_day(cb: CallbackQuery, storage: TelegramStorage):
    _, date, pair_index = cb.data.split("|")
    pair_index = int(pair_index)
    await cb.answer()

    # Disable keyboard in original message
    state = await storage.load()
    day = state["dates"][date]
    tasks = day["tasks"]

    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks.values() if t.get("done"))
    percentage = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0

    # Post summary to group
    from storage import render_text, build_keyboard
    summary_text = render_text(date, tasks, title=f"🏁 {cb.from_user.first_name}'s Day Finished! ({percentage}%)")

    if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
        await cb.bot.send_message(
            config.GROUP_CHAT_ID,
            summary_text,
            message_thread_id=config.TOPIC_THREAD_ID,
        )

    # Re-render with finished=True to remove the inline keyboard
    text = render_text(date, tasks)
    kb = build_keyboard(date, pair_index, tasks, finished=True)

    pair = day["pairs"][pair_index]
    target = pair.get("dm")
    if target:
        from storage import safe_edit_message
        await safe_edit_message(
            storage.bot, target["chat_id"], target["message_id"], text, kb
        )

    await cb.message.answer(f"🏁 Day finished! You completed {done_tasks}/{total_tasks} ({percentage}%) targets.")


# --------------------------------------------------------------------------- #
#  Question entry flow
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("qs|"))
async def questions_prompt(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    _, date, pair_index, task_id = cb.data.split("|")

    # Check if already done
    store_state = await storage.load()
    task = store_state["dates"][date]["tasks"][task_id]
    if task.get("done"):
        return await cb.answer("Already completed! 🎉")

    await state.set_state(QuestionInput.waiting)
    await state.update_data(date=date, pair_index=int(pair_index), task_id=task_id)
    await cb.answer()

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            f"✍️ How many more questions did you solve? (Total: {task.get('total_q')})",
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

    # Need to add to existing solved amount
    store_state = await storage.load()
    task = store_state["dates"][data["date"]]["tasks"][data["task_id"]]
    new_solved = task.get("solved_q", 0) + solved

    done = await storage.set_questions_solved(data["date"], data["pair_index"], data["task_id"], new_solved)
    if done:
        await m.answer(f"🎉 Questions completed!")
    else:
        await m.answer(f"📝 Progress recorded: {new_solved}/{task.get('total_q')} questions")


@router.message(QuestionInput.waiting)
async def questions_invalid(m: Message):
    await m.answer("Please send a valid number.")


# --------------------------------------------------------------------------- #
#  Finish Day
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("finish|"))
async def finish_day(cb: CallbackQuery, storage: TelegramStorage):
    _, date, pair_index = cb.data.split("|")
    pair_index = int(pair_index)
    await cb.answer()

    # Disable keyboard in original message
    state = await storage.load()
    day = state["dates"][date]
    tasks = day["tasks"]

    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks.values() if t.get("done"))
    percentage = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0

    # Save state to finish
    day["finished"] = True
    await storage.save(state)

    # Post summary to group
    from storage import render_text, build_keyboard
    summary_text = render_text(date, tasks, title=f"🏁 {cb.from_user.first_name}'s Day Finished! ({percentage}%)")

    if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
        await cb.bot.send_message(
            config.GROUP_CHAT_ID,
            summary_text,
            message_thread_id=config.TOPIC_THREAD_ID,
        )

    # Re-render with finished=True to remove the inline keyboard from both
    text = render_text(date, tasks)
    kb = build_keyboard(date, pair_index, tasks, finished=True)

    pair = day["pairs"][pair_index]
    from storage import safe_edit_message
    import asyncio
    jobs = []
    for side in ("dm", "topic"):
        target = pair.get(side)
        if target:
            jobs.append(safe_edit_message(
                storage.bot, target["chat_id"], target["message_id"], text, kb
            ))
    await asyncio.gather(*jobs)

    await cb.message.answer(f"🏁 Day finished! You completed {done_tasks}/{total_tasks} ({percentage}%) targets.")


# --------------------------------------------------------------------------- #
#  Question entry flow
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("qs|"))
async def questions_prompt(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    _, date, pair_index, task_id = cb.data.split("|")

    # Check if already done
    store_state = await storage.load()
    task = store_state["dates"][date]["tasks"][task_id]
    if task.get("done"):
        return await cb.answer("Already completed! 🎉")

    await state.set_state(QuestionInput.waiting)
    await state.update_data(date=date, pair_index=int(pair_index), task_id=task_id)
    await cb.answer()

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            f"✍️ How many more questions did you solve? (Total: {task.get('total_q')})",
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

    # Need to add to existing solved amount
    store_state = await storage.load()
    task = store_state["dates"][data["date"]]["tasks"][data["task_id"]]
    new_solved = task.get("solved_q", 0) + solved

    done = await storage.set_questions_solved(data["date"], data["pair_index"], data["task_id"], new_solved)
    if done:
        await m.answer(f"🎉 Questions completed!")
    else:
        await m.answer(f"📝 Progress recorded: {new_solved}/{task.get('total_q')} questions")


@router.message(QuestionInput.waiting)
async def questions_invalid(m: Message):
    await m.answer("Please send a valid number.")


# --------------------------------------------------------------------------- #
#  Finish Day
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("finish|"))
async def finish_day(cb: CallbackQuery, storage: TelegramStorage):
    _, date, pair_index = cb.data.split("|")
    pair_index = int(pair_index)
    await cb.answer()

    # Disable keyboard in original message
    state = await storage.load()
    day = state["dates"][date]
    tasks = day["tasks"]

    total_tasks = len(tasks)
    done_tasks = sum(1 for t in tasks.values() if t.get("done"))
    percentage = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0

    # Save state to finish
    day["finished"] = True
    await storage.save(state)

    # Post summary to group
    from storage import render_text, build_keyboard
    summary_text = render_text(date, tasks, title=f"🏁 {cb.from_user.first_name}'s Day Finished! ({percentage}%)")

    if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
        await cb.bot.send_message(
            config.GROUP_CHAT_ID,
            summary_text,
            message_thread_id=config.TOPIC_THREAD_ID,
        )

    # Re-render with finished=True to remove the inline keyboard from both
    text = render_text(date, tasks)
    kb = build_keyboard(date, pair_index, tasks, finished=True)

    pair = day["pairs"][pair_index]
    from storage import safe_edit_message
    import asyncio
    jobs = []
    for side in ("dm", "topic"):
        target = pair.get(side)
        if target:
            jobs.append(safe_edit_message(
                storage.bot, target["chat_id"], target["message_id"], text, kb
            ))
    await asyncio.gather(*jobs)

    await cb.message.answer(f"🏁 Day finished! You completed {done_tasks}/{total_tasks} ({percentage}%) targets.")


# --------------------------------------------------------------------------- #
#  Score entry flow
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

    # 48-Hour lock check
    if is_date_locked(date):
        return await cb.answer("🔒 Locked: Targets older than 48 hours are finalized and cannot be edited.", show_alert=True)

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

    if is_date_locked(date):
        return await m.answer("🔒 Locked: Targets older than 48 hours can no longer be edited.")

    await storage.set_score(owner_id, date, pair_index, task_id, score)
    await m.answer(f"🎉 Score recorded: <b>{score}</b>")
    if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
        await m.bot.send_message(
            config.GROUP_CHAT_ID,
            f"🎊 <b>{m.from_user.first_name}</b> scored <b>{score}</b> on today's test!",
            message_thread_id=config.TOPIC_THREAD_ID,
        )


@router.message(ScoreInput.waiting)
async def score_invalid(m: Message):
    await m.answer("That doesn't look like a score. Send it as <b>610/720</b>:")


# --------------------------------------------------------------------------- #
#  Deletion functionality (per-user)
# --------------------------------------------------------------------------- #
@router.message(Command("delete"))
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

    if is_date_locked(date):
        return await m.answer(f"🔒 Targets for <code>{date}</code> are older than 48 hours and locked.")

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

    if is_date_locked(date):
        return await cb.answer("🔒 Targets older than 48 hours are locked.", show_alert=True)

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