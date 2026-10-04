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
#  Interactive Help Callbacks
# --------------------------------------------------------------------------- #
def get_main_help_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(inline_keyboard=[
        [
            InlineKeyboardButton(text="📱 Web App Guide", callback_data="help_topic|webapp"),
            InlineKeyboardButton(text="⚡ Quick Syntax (/q)", callback_data="help_topic|quick"),
        ],
        [
            InlineKeyboardButton(text="🔗 Group Sync (/set)", callback_data="help_topic|group"),
            InlineKeyboardButton(text="📊 Reports & Export", callback_data="help_topic|reports"),
        ],
    ])


@router.callback_query(F.data == "help_menu")
async def help_menu_back(cb: CallbackQuery):
    await cb.answer()
    text = (
        "📖 <b>Daily Target Tracker — Help Center</b>\n\n"
        "Tap a topic below to see quick instructions:"
    )
    await cb.message.edit_text(text, reply_markup=get_main_help_keyboard())


@router.callback_query(F.data.startswith("help_topic|"))
async def help_topic_view(cb: CallbackQuery):
    topic = cb.data.split("|")[1]
    await cb.answer()

    back_kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Back to Help Menu", callback_data="help_menu")]
    ])

    if topic == "webapp":
        content = (
            "📱 <b>Telegram Mini App (WebApp) Guide</b>\n\n"
            "• Tap <b>'Open Web App'</b> at the bottom of the chat to launch.\n"
            "• Select your <b>Subject</b> (Physics, Chemistry, Biology, Test, or Custom).\n"
            "• Optionally type a <b>Chapter name</b> (e.g. <i>Thermodynamics</i>).\n"
            "• Choose task type: <b>Lectures</b> (auto-splits counts), <b>Questions</b>, or <b>Revision</b>.\n"
            "• Tap <b>'➕ Add Task to List'</b> to queue multiple tasks.\n"
            "• Tap <b>'🚀 Send All Targets'</b> to publish everything in one click!"
        )
    elif topic == "quick":
        content = (
            "⚡ <b>Quick Syntax (/target or /q)</b>\n\n"
            "Fastest way to create multiple targets:\n"
            "<code>/target phy L2 Q50 ncert Thermodynamics</code>\n\n"
            "<b>Tags supported:</b>\n"
            "• <code>phy</code> / <code>chem</code> / <code>bio</code> — Sets subject\n"
            "• <code>L2</code> — Creates Lecture 1 & Lecture 2\n"
            "• <code>Q50</code> — Sets 50 question tracker with fraction progress\n"
            "• <code>ncert</code> / <code>rev</code> / <code>notes</code> — Quick revision tasks\n"
            "• Any extra words become the <b>Chapter/Topic name</b>!"
        )
    elif topic == "group":
        content = (
            "🔗 <b>Group & Topic Sync (/set)</b>\n\n"
            "• Add this bot to your study group.\n"
            "• Open the specific forum topic where you want your targets sent.\n"
            "• Send <code>/set</code> inside that topic.\n"
            "• <b>Group Study:</b> Multiple friends can send <code>/set</code> in the same topic. "
            "Each person gets their own distinct checklist, and friends cannot accidentally click your buttons!"
        )
    elif topic == "reports":
        content = (
            "📊 <b>Reports, Summary & Export</b>\n\n"
            "• <code>/summary</code> — View your recent study streak & question stats.\n"
            "• <b>In Groups:</b> Reply to any friend's message with <code>/summary</code> to check their 5-day study progress!\n"
            "• <code>/export</code> — Generates an interactive, standalone HTML study dashboard file with Dark/Light mode and subject filter tabs!\n"
            "• <b>48-Hour Rule:</b> Targets can be edited up to 48 hours after creation, after which they are permanently locked."
        )
    else:
        content = "Select a topic from the menu."

    await cb.message.edit_text(content, reply_markup=back_kb)


# --------------------------------------------------------------------------- #
#  /summary Command (Check own or peer study summary)
# --------------------------------------------------------------------------- #
@router.message(Command("summary", "stats"))
async def cmd_summary(m: Message, storage: TelegramStorage):
    target_user = m.from_user

    # If replied to someone in group, show that user's summary!
    if m.reply_to_message and m.reply_to_message.from_user and not m.reply_to_message.from_user.is_bot:
        target_user = m.reply_to_message.from_user

    user_id = target_user.id
    user_name = target_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={user_id}\">{escaped_name}</a>"

    state = await storage.load(user_id)
    dates_data = state.get("dates", {})

    if not dates_data:
        return await m.reply(f"ℹ️ No study targets recorded yet for {user_link}.")

    # Get last 5 recorded days
    sorted_days = sorted(dates_data.keys(), reverse=True)[:5]

    total_tasks = 0
    done_tasks = 0
    total_q = 0
    solved_q = 0
    lines = [f"📊 <b>5-Day Study Report for {user_link}</b>", "──────────────────────────────"]

    for d in sorted_days:
        day_tasks = dates_data[d].get("tasks", {})
        d_tot = len(day_tasks)
        d_done = sum(1 for t in day_tasks.values() if t.get("done"))
        total_tasks += d_tot
        done_tasks += d_done

        # Question and score summaries for the day
        d_qs_solved = 0
        d_qs_tot = 0
        d_scores = []
        for t in day_tasks.values():
            if t.get("kind") == "questions":
                d_qs_tot += t.get("total_q", 0)
                d_qs_solved += t.get("solved_q", 0)
            if t.get("kind") == "score" and t.get("score"):
                d_scores.append(t["score"])

        total_q += d_qs_tot
        solved_q += d_qs_solved

        pct = int((d_done / d_tot * 100)) if d_tot > 0 else 0
        status_mark = "✅" if (d_done == d_tot and d_tot > 0) else "⏳"

        day_line = f"🗓️ <code>{d}</code>: {d_done}/{d_tot} ({pct}%) {status_mark}"
        if d_qs_tot > 0:
            day_line += f" • ✍️ {d_qs_solved}/{d_qs_tot} Qs"
        if d_scores:
            day_line += f" • 🏆 {d_scores[0]}"

        lines.append(day_line)

    lines.append("──────────────────────────────")
    overall_pct = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0
    lines.append(f"🔥 <b>Active Days:</b> {len(sorted_days)} recorded")
    lines.append(f"📈 <b>Average Completion:</b> {overall_pct}% ({done_tasks}/{total_tasks} tasks)")
    if total_q > 0:
        lines.append(f"🎯 <b>Total Questions Solved:</b> {solved_q} / {total_q}")

    await m.reply("\n".join(lines))


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
#  Question entry flow (dual-sync + authorization + 48h lock)
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

    # 48-Hour lock check
    if is_date_locked(date):
        return await cb.answer("🔒 Locked: Targets older than 48 hours are finalized and cannot be edited.", show_alert=True)

    store_state = await storage.load(owner_id)
    task = store_state.get("dates", {}).get(date, {}).get("tasks", {}).get(task_id, {})
    if task.get("done"):
        return await cb.answer("Already completed! 🎉")

    await state.set_state(QuestionInput.waiting)
    await state.update_data(owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id)
    await cb.answer()

    total_q = task.get("total_q", 0)
    current_q = task.get("solved_q", 0)

    try:
        await cb.bot.send_message(
            cb.from_user.id,
            f"✍️ <b>Question Progress</b> (Target: {total_q})\n"
            f"Currently solved: <b>{current_q} / {total_q}</b>\n\n"
            "Send the total questions solved so far (e.g. <code>50</code>) or send <code>+10</code> to add more:",
        )
    except Exception:
        await cb.answer(
            "Open a DM with me first, then tap the button again.",
            show_alert=True,
        )


@router.message(QuestionInput.waiting, F.text.regexp(r"^\+?\d+$"))
async def questions_received(m: Message, state: FSMContext, storage: TelegramStorage):
    raw_text = m.text.strip()
    data = await state.get_data()
    await state.clear()

    owner_id = data["owner_id"]
    date = data["date"]
    pair_index = data["pair_index"]
    task_id = data["task_id"]

    if is_date_locked(date):
        return await m.answer("🔒 Locked: Targets older than 48 hours can no longer be edited.")

    store_state = await storage.load(owner_id)
    task = store_state.get("dates", {}).get(date, {}).get("tasks", {}).get(task_id, {})

    if raw_text.startswith("+"):
        # Incremental addition
        delta = int(raw_text[1:])
        new_solved = task.get("solved_q", 0) + delta
    else:
        # Absolute count
        new_solved = int(raw_text)

    done = await storage.set_questions_solved(owner_id, date, pair_index, task_id, new_solved)
    if done:
        await m.answer("🎉 Target completed!")
    else:
        await m.answer(f"📝 Progress recorded: {new_solved}/{task.get('total_q', 0)} questions")


@router.message(QuestionInput.waiting)
async def questions_invalid(m: Message):
    await m.answer("Please send a valid number (e.g. <code>50</code> or <code>+10</code>).")


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