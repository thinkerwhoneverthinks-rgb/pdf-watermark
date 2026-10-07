"""Callbacks: ticking tasks, dual-sync edits, click authorization, 48h locks, /summary, and interactive help."""

import datetime
import html
from aiogram import F, Router
from aiogram.filters import Command
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.base import StorageKey
from aiogram.types import CallbackQuery, Message, InlineKeyboardButton, InlineKeyboardMarkup

import config
from storage import TelegramStorage, is_date_locked, today_str, tomorrow_str, render_text

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
# --------------------------------------------------------------------------- #
#  Question entry flow (dual-sync + authorization + 48h lock + group updates)
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

    total_q = task.get("total_q", 0)
    current_q = task.get("solved_q", 0)
    task_label = task.get("label", "Questions")

    # Set state for DM chat so sending question numbers in DM works 100%
    dm_key = StorageKey(bot_id=cb.bot.id, chat_id=owner_id, user_id=owner_id)
    dm_state = FSMContext(storage=state.storage, key=dm_key)
    await dm_state.set_state(QuestionInput.waiting)
    await dm_state.update_data(
        owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id,
        task_label=task_label, total_q=total_q
    )

    # If tapped in a group, also set state on the group chat context
    if cb.message.chat.id != owner_id:
        await state.set_state(QuestionInput.waiting)
        await state.update_data(
            owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id,
            task_label=task_label, total_q=total_q
        )

    await cb.answer()

    # Send prompt to user in private DM
    try:
        await cb.bot.send_message(
            owner_id,
            f"✍️ <b>Question Progress</b> (Target: {total_q})\n"
            f"Task: <b>{html.escape(task_label)}</b>\n"
            f"Currently solved: <b>{current_q} / {total_q}</b>\n\n"
            "Send the total questions solved so far (e.g. <code>50</code>) or send <code>+10</code> to add more:",
        )
    except Exception:
        pass

    # Send message in group reporting current solved count and prompting for update
    user_name = store_state.get("user_name") or cb.from_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={owner_id}\">{escaped_name}</a>"

    cfg = store_state.get("config", {})
    if cb.message.chat.type in ("group", "supergroup"):
        group_id = cb.message.chat.id
        topic_id = cb.message.message_thread_id
    else:
        group_id = cfg.get("group_chat_id") or config.GROUP_CHAT_ID
        topic_id = cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

    if group_id:
        try:
            await cb.bot.send_message(
                group_id,
                f"✍️ <b>Question Progress</b> • {user_link}\n"
                f"Task: <b>{html.escape(task_label)}</b>\n"
                f"Currently solved: <b>{current_q} / {total_q}</b>\n\n"
                "Send the total questions solved so far (e.g. <code>50</code> or <code>+10</code>) in DM or reply here:",
                message_thread_id=topic_id,
            )
        except Exception:
            pass


@router.message(QuestionInput.waiting, F.text.regexp(r"^\+?\d+$"))
async def questions_received(m: Message, state: FSMContext, storage: TelegramStorage):
    raw_text = m.text.strip()
    data = await state.get_data()

    # Fallback to DM state if message came in private DM but callback was elsewhere
    if not data or "owner_id" not in data:
        dm_key = StorageKey(bot_id=m.bot.id, chat_id=m.from_user.id, user_id=m.from_user.id)
        dm_state = FSMContext(storage=state.storage, key=dm_key)
        data = await dm_state.get_data()

    # Clear both contexts so user is not stuck in state
    await state.clear()
    dm_key = StorageKey(bot_id=m.bot.id, chat_id=m.from_user.id, user_id=m.from_user.id)
    dm_state = FSMContext(storage=state.storage, key=dm_key)
    await dm_state.clear()

    if not data or "owner_id" not in data:
        return await m.answer("⚠️ No active question session. Tap the questions button on your checklist first.")

    owner_id = data["owner_id"]
    date = data["date"]
    pair_index = data["pair_index"]
    task_id = data["task_id"]

    if is_date_locked(date):
        return await m.answer("🔒 Locked: Targets older than 48 hours can no longer be edited.")

    store_state = await storage.load(owner_id)
    task = store_state.get("dates", {}).get(date, {}).get("tasks", {}).get(task_id, {})
    total_q = task.get("total_q", data.get("total_q", 0))
    task_label = task.get("label", data.get("task_label", "Questions"))

    if raw_text.startswith("+"):
        delta = int(raw_text[1:])
        new_solved = task.get("solved_q", 0) + delta
    else:
        new_solved = int(raw_text)

    done = await storage.set_questions_solved(owner_id, date, pair_index, task_id, new_solved)

    if done:
        feedback = f"🎉 Target completed! (<b>{min(new_solved, total_q)}/{total_q}</b> questions — {html.escape(task_label)})"
    else:
        feedback = f"📝 Progress recorded: <b>{new_solved}/{total_q}</b> questions ({html.escape(task_label)})"

    await m.answer(feedback)

    # Post question update to the linked group topic as well
    user_name = store_state.get("user_name") or m.from_user.full_name
    escaped_name = html.escape(user_name)
    user_link = f"<a href=\"tg://user?id={owner_id}\">{escaped_name}</a>"

    cfg = store_state.get("config", {})
    group_id = cfg.get("group_chat_id") or config.GROUP_CHAT_ID
    topic_id = cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

    if group_id:
        try:
            if done:
                group_msg = f"🎉 {user_link} completed target: <b>{min(new_solved, total_q)}/{total_q}</b> questions ({html.escape(task_label)})! 🔥"
            else:
                group_msg = f"📝 {user_link} solved <b>{new_solved}/{total_q}</b> questions ({html.escape(task_label)})! 🎯"
            await m.bot.send_message(
                group_id,
                group_msg,
                message_thread_id=topic_id,
            )
        except Exception:
            pass


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

    # Set state for DM chat so sending scores in DM works 100%
    dm_key = StorageKey(bot_id=cb.bot.id, chat_id=owner_id, user_id=owner_id)
    dm_state = FSMContext(storage=state.storage, key=dm_key)
    await dm_state.set_state(ScoreInput.waiting)
    await dm_state.update_data(owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id)

    if cb.message.chat.id != owner_id:
        await state.set_state(ScoreInput.waiting)
        await state.update_data(owner_id=owner_id, date=date, pair_index=pair_index, task_id=task_id)

    await cb.answer()

    try:
        await cb.bot.send_message(
            owner_id,
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
    if not data or "owner_id" not in data:
        dm_key = StorageKey(bot_id=m.bot.id, chat_id=m.from_user.id, user_id=m.from_user.id)
        dm_state = FSMContext(storage=state.storage, key=dm_key)
        data = await dm_state.get_data()

    await state.clear()
    dm_key = StorageKey(bot_id=m.bot.id, chat_id=m.from_user.id, user_id=m.from_user.id)
    dm_state = FSMContext(storage=state.storage, key=dm_key)
    await dm_state.clear()

    if not data or "owner_id" not in data:
        return await m.answer("⚠️ No active score session. Tap the score button on your checklist first.")

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
#  Deletion functionality (per-user & individual task deletion)
# --------------------------------------------------------------------------- #
def build_delete_keyboard(user_id: int, date: str, tasks: dict) -> InlineKeyboardMarkup:
    rows = []
    for task_id, task in tasks.items():
        time_hint = f" [{task['time_slot']}]" if task.get("time_slot") else ""
        label = f"🗑️ {task.get('label', 'Task')}{time_hint}"
        cb_data = f"deltask|{user_id}|{date}|{task_id}"
        rows.append([
            InlineKeyboardButton(text=label[:60], callback_data=cb_data[:64])
        ])
    rows.append([
        InlineKeyboardButton(text="💥 Delete All Targets", callback_data=f"deldate_confirm|{user_id}|{date}")
    ])
    rows.append([
        InlineKeyboardButton(text="❌ Close / Done", callback_data="deldate_cancel")
    ])
    return InlineKeyboardMarkup(inline_keyboard=rows)


@router.message(Command("delete"), F.chat.type == "private")
async def cmd_delete_date(m: Message, storage: TelegramStorage):
    """Delete individual targets or all targets for a date from user's state."""
    text = m.text.strip()
    args = text.split()
    user_id = m.from_user.id

    state = await storage.load(user_id)
    user_dates = state.get("dates", {})

    if len(args) > 1:
        first_arg = args[1].lower()
        if first_arg == "tomorrow":
            date = tomorrow_str()
        elif first_arg == "today":
            date = today_str()
        else:
            date = args[1]
    else:
        # Default to today; if today has no targets and tomorrow has targets, choose tomorrow
        if today_str() in user_dates and user_dates[today_str()].get("tasks"):
            date = today_str()
        elif tomorrow_str() in user_dates and user_dates[tomorrow_str()].get("tasks"):
            date = tomorrow_str()
        else:
            date = today_str()

    if is_date_locked(date):
        return await m.answer(f"🔒 Targets for <code>{date}</code> are older than 48 hours and locked.")

    day = user_dates.get(date)
    if not day or not day.get("tasks"):
        return await m.answer(
            f"❌ No targets found for <code>{date}</code>.\n\n"
            "Tip: You can specify dates like <code>/delete tomorrow</code> or <code>/delete YYYY-MM-DD</code>."
        )

    text_content = (
        f"🗑️ <b>Manage / Delete Targets</b> • <code>{date}</code>\n\n"
        "Tap an individual target below to delete it, or choose <b>Delete All</b>:"
    )
    kb = build_delete_keyboard(user_id, date, day["tasks"])
    await m.answer(text_content, reply_markup=kb)


@router.callback_query(F.data.startswith("deltask|"))
async def delete_single_task(cb: CallbackQuery, storage: TelegramStorage):
    """Delete an individual target and refresh the deletion menu."""
    parts = cb.data.split("|")
    owner_id = int(parts[1])
    date = parts[2]
    task_id = parts[3]

    if cb.from_user.id != owner_id:
        return await cb.answer("⚠️ You can only delete your own targets.", show_alert=True)

    if is_date_locked(date):
        return await cb.answer("🔒 Targets older than 48 hours are locked.", show_alert=True)

    success = await storage.delete_task(owner_id, date, task_id)
    if not success:
        return await cb.answer("❌ Could not delete target (already removed or locked).", show_alert=True)

    await cb.answer("🗑️ Target deleted!")

    # Reload state to check if more tasks remain
    state = await storage.load(owner_id)
    day = state.get("dates", {}).get(date)
    if day and day.get("tasks"):
        text_content = (
            f"🗑️ <b>Manage / Delete Targets</b> • <code>{date}</code>\n\n"
            "Tap an individual target below to delete it, or choose <b>Delete All</b>:"
        )
        kb = build_delete_keyboard(owner_id, date, day["tasks"])
        await cb.message.edit_text(text_content, reply_markup=kb)
    else:
        await cb.message.edit_text(f"✅ All targets for <code>{date}</code> have been removed.", reply_markup=None)


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
        await cb.message.edit_text(f"✅ All targets for <code>{date}</code> have been deleted!", reply_markup=None)
    else:
        await cb.message.edit_text("❌ Failed to delete targets")


@router.callback_query(F.data == "deldate_cancel")
async def cancel_delete(cb: CallbackQuery):
    await cb.answer()
    await cb.message.edit_text("✅ Target deletion menu closed.", reply_markup=None)