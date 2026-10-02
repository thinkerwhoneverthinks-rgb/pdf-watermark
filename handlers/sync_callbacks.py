"""Callbacks: ticking tasks, dual-sync edits, and test score entry."""

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, Message

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
