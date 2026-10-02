"""Callbacks: ticking tasks, dual-sync edits, and test score entry."""

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


# --------------------------------------------------------------------------- #
#  Toggling tasks (dual-sync)
# --------------------------------------------------------------------------- #
@router.callback_query(F.data == "noop")
async def noop(cb: CallbackQuery):
    await cb.answer("Already recorded 🎉")


@router.callback_query(F.data.startswith("tg|"))
async def toggle(cb: CallbackQuery, storage: TelegramStorage):
    _, date, pair_index, task_id = cb.data.split("|")
    await cb.answer()  # answer fast; the edits below can take a moment
    done = await storage.toggle_task(date, int(pair_index), task_id)
    if done:
        await cb.answer("Done! 💪")
    # (second answer is a no-op on clients; first answer already stopped the spinner)


# --------------------------------------------------------------------------- #
#  Score entry flow
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("sc|"))
async def score_prompt(cb: CallbackQuery, state: FSMContext):
    _, date, pair_index, task_id = cb.data.split("|")
    await state.set_state(ScoreInput.waiting)
    await state.update_data(date=date, pair_index=int(pair_index), task_id=task_id)
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
    await storage.set_score(data["date"], data["pair_index"], data["task_id"], score)
    await m.answer(f"🎉 Score recorded: <b>{score}</b>")
    if config.GROUP_CHAT_ID and config.TOPIC_ID:
        await m.bot.send_message(
            config.GROUP_CHAT_ID,
            f"🎊 <b>{m.from_user.first_name}</b> scored <b>{score}</b> on today's test!",
            message_thread_id=config.TOPIC_ID,
        )


@router.message(ScoreInput.waiting)
async def score_invalid(m: Message):
    await m.answer("That doesn't look like a score. Send it as <b>610/720</b>:")


# --------------------------------------------------------------------------- #
#  Deletion functionality
# --------------------------------------------------------------------------- #
@router.callback_query(F.data.startswith("deltask|"))
async def delete_single_task(cb: CallbackQuery, storage: TelegramStorage):
    """Delete a single task from the checklist."""
    _, date, pair_index, task_id = cb.data.split("|")
    pair_index = int(pair_index)
    
    await cb.answer()
    success = await storage.delete_task(date, task_id, pair_index)
    
    if success:
        await cb.answer("🗑️ Task deleted!")
    else:
        await cb.answer("❌ Failed to delete task")


@router.message(Command("delete"))
async def cmd_delete_date(m: Message, storage: TelegramStorage):
    """Delete all targets for a specific date.
    Usage: /delete 2026-10-02
    Or: /delete (shows today's targets to delete)
    """
    from storage import today_str
    text = m.text.strip()
    args = text.split()
    
    if len(args) > 1:
        # User provided a date
        date = args[1]
    else:
        # Show today's targets with delete confirmation
        date = today_str()
    
    state = await storage.load()
    day = state.get("dates", {}).get(date)
    
    if not day or not day.get("tasks"):
        return await m.answer(f"❌ No targets found for <code>{date}</code>")
    
    # Show targets and ask for confirmation
    from storage import render_text
    text_content = render_text(date, day["tasks"], title="🗑️ Delete these targets?")
    
    kb = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="✅ Yes, Delete All", callback_data=f"deldate_confirm|{date}"),
        InlineKeyboardButton(text="❌ Cancel", callback_data="deldate_cancel"),
    ]])
    
    await m.answer(text_content, reply_markup=kb)


@router.callback_query(F.data.startswith("deldate_confirm|"))
async def confirm_delete_date(cb: CallbackQuery, storage: TelegramStorage):
    """Confirm and execute deletion of entire date."""
    date = cb.data.split("|")[1]
    await cb.answer()
    
    success = await storage.delete_date(date)
    
    if success:
        await cb.message.edit_text(f"✅ All targets for <code>{date}</code> have been deleted!")
    else:
        await cb.message.edit_text("❌ Failed to delete targets")


@router.callback_query(F.data == "deldate_cancel")
async def cancel_delete(cb: CallbackQuery):
    """Cancel deletion."""
    await cb.answer()
    await cb.message.edit_text("❌ Deletion cancelled")