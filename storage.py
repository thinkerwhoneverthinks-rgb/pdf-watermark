"""Telegram-as-a-database storage layer.

Supports multi-user tracking with zero external database.
Each user's state lives in their own pinned Telegram message in their private DM
with the bot, prefixed with STATE_MARKER. Whenever anything changes we re-serialize
the state and edit the pinned message in place, surviving Render free-tier sleeps,
server restarts, and redeployments.
"""

import asyncio
import datetime
import html
import json
import logging
import uuid
from typing import Any, Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config

log = logging.getLogger("dtt-storage")
MAX_EDIT_ATTEMPTS = 3

PINNED_BANNER = (
    "📌 <b>Daily Target Tracker Storage</b>\n"
    "⚠️ <b>DO NOT DELETE OR UNPIN THIS MESSAGE!</b>\n"
    "<i>This message securely stores your study streaks, targets, and test scores.</i>\n"
    "───────────────────────────────────\n"
)


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #
def new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def today_str() -> str:
    return datetime.date.today().isoformat()

def get_relative_date_str(days_ahead: int) -> str:
    return (datetime.date.today() + datetime.timedelta(days=days_ahead)).isoformat()


async def safe_edit_message(bot: Bot, chat_id: int, message_id: int,
                            text: str, reply_markup=None) -> bool:
    """Edit a message, gracefully riding out Telegram rate limits."""
    for _ in range(MAX_EDIT_ATTEMPTS):
        try:
            await bot.edit_message_text(
                text=text, chat_id=chat_id, message_id=message_id,
                reply_markup=reply_markup,
            )
            return True
        except TelegramRetryAfter as exc:
            await asyncio.sleep(exc.retry_after + 0.5)
        except TelegramBadRequest as exc:
            if "not modified" in str(exc).lower():
                return True
            return False
        except TelegramNotFound:
            return False
        except Exception as exc:
            log.warning("safe_edit_message error on chat %s msg %s: %s", chat_id, message_id, exc)
            return False
    return False


# --------------------------------------------------------------------------- #
#  Rendering
# --------------------------------------------------------------------------- #
def build_keyboard(date: str, pair_index: int, tasks: Dict[str, dict], finished: bool = False) -> InlineKeyboardMarkup:
    if finished:
        return InlineKeyboardMarkup(inline_keyboard=[])

    rows = []
    for task_id, task in tasks.items():
        if task.get("kind") == "score":
            if task.get("score"):
                label, cb = f"✅ Scored: {task['score']}", "noop"
            else:
                label, cb = "📝 Enter Score", f"sc|{user_id}|{date}|{pair_index}|{task_id}"
            rows.append([InlineKeyboardButton(text=label[:64], callback_data=cb[:64])])
        elif task.get("kind") == "questions":
            total = task.get("total_q", 0)
            solved = task.get("solved_q", 0)
            mark = "✅" if task.get("done") else "⬜"
            label, cb = f"{mark} {task['label']} ({solved}/{total})", f"qs|{user_id}|{date}|{pair_index}|{task_id}"
            rows.append([InlineKeyboardButton(text=label[:64], callback_data=cb[:64])])
        elif task.get("kind") == "questions":
            total = task.get("total_q", 0)
            solved = task.get("solved_q", 0)
            mark = "✅" if task.get("done") else "❌"
            label, cb = f"{mark} {task['label']} ({solved}/{total})", f"qs|{date}|{pair_index}|{task_id}"
            rows.append([InlineKeyboardButton(text=label[:64], callback_data=cb[:64])])
        elif task.get("kind") == "questions":
            total = task.get("total_q", 0)
            solved = task.get("solved_q", 0)
            mark = "✅" if task.get("done") else "❌"
            label, cb = f"{mark} {task['label']} ({solved}/{total})", f"qs|{date}|{pair_index}|{task_id}"
            rows.append([InlineKeyboardButton(text=label[:64], callback_data=cb[:64])])
        else:
            mark = "✅" if task.get("done") else "❌"
            label, cb = f"{mark} {task['label']}", f"tg|{date}|{pair_index}|{task_id}"
            
            rows.append([
                InlineKeyboardButton(text=label[:64], callback_data=cb[:64])
            ])

    # Add Finish Day button
    rows.append([InlineKeyboardButton(text="🏁 Finish Day", callback_data=f"finish|{date}|{pair_index}")])
    return InlineKeyboardMarkup(inline_keyboard=rows)


def render_text(date: str, tasks: Dict[str, dict], user_id: Optional[int] = None, user_name: Optional[str] = None, title: Optional[str] = None) -> str:
    done = sum(1 for t in tasks.values() if t.get("done"))
    locked_tag = " [🔒 Locked]" if is_date_locked(date) else ""

    if title:
        header = f"<b>{title}</b> • <code>{date}</code>{locked_tag}"
    elif user_id and user_name:
        escaped_name = html.escape(user_name)
        header = f"🎯 <a href=\"tg://user?id={user_id}\">{escaped_name}</a>'s Targets • <code>{date}</code>{locked_tag}"
    elif user_name:
        header = f"🎯 <b>{html.escape(user_name)}'s Targets</b> • <code>{date}</code>{locked_tag}"
    else:
        header = f"🎯 <b>Daily Targets</b> • <code>{date}</code>{locked_tag}"

    lines = [header, ""]
    for task in tasks.values():
        if task.get("kind") == "score":
            status = f"🏆 {task['score']}" if task.get("score") else "📝 awaiting score"
        elif task.get("kind") == "questions":
            total = task.get("total_q", 0)
            solved = task.get("solved_q", 0)
            status = "✅" if task.get("done") else "⬜"
            lines.append(f"{status} {task['label']} ({solved}/{total})")
            continue
        else:
            status = "✅" if task.get("done") else "⬜"
        lines.append(f"{status} {task['label']}")
    lines += ["", f"Progress: <b>{done}/{len(tasks)}</b> complete"]
    return "\n".join(lines)


# --------------------------------------------------------------------------- #
#  Storage
# --------------------------------------------------------------------------- #
class TelegramStorage:
    """Multi-user JSON state persisted inside each user's pinned DM message."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self._user_locks: Dict[int, asyncio.Lock] = {}
        self._user_caches: Dict[int, Dict[str, Any]] = {}
        self._user_msg_ids: Dict[int, int] = {}

    def _get_lock(self, user_id: int) -> asyncio.Lock:
        if user_id not in self._user_locks:
            self._user_locks[user_id] = asyncio.Lock()
        return self._user_locks[user_id]

    async def init(self) -> None:
        raw = await self._read_raw()
        if raw is None:
            prefix = "📌 Daily Target Tracker Storage ⚠️ DO NOT DELETE OR UNPIN THIS MESSAGE\n\n"
            sent = await self.bot.send_message(
                self.chat_id, prefix + config.STATE_MARKER + "{}",
                message_thread_id=self.thread_id,
            )
            try:
                await self.load(config.STATE_CHAT_ID)
            except Exception:
                pass
            self._state_msg_id = sent.message_id
            raw = config.STATE_MARKER + "{}"
        self._cache = self._parse(raw)

    async def _read_raw(self) -> Optional[str]:
        chat = await self.bot.get_chat(self.chat_id)
        pinned = getattr(chat, "pinned_message", None)

        # Aiogram 3 Message objects might not have `text` directly if it's not a text message,
        # but in our case it should be. However, the logic here requires the bot to fetch the chat
        # and get the pinned message. Let's make sure we handle cases where state isn't found gracefully.
        if pinned and pinned.text and config.STATE_MARKER in pinned.text:
            self._state_msg_id = pinned.message_id
            # Extract from the marker onwards in case of prepended warnings
            marker_idx = pinned.text.find(config.STATE_MARKER)
            return pinned.text[marker_idx:]

        # If no pinned message or doesn't match marker, try to search recent messages in the chat
        # In this simple bot, we'll just return None to recreate it, which is safer.
        return None

    @staticmethod
    def _parse(raw: str) -> Dict[str, Any]:
        try:
            return json.loads(raw[len(config.STATE_MARKER):])
        except Exception:
            return {"config": {}, "dates": {}}

    async def load(self, user_id: int) -> Dict[str, Any]:
        lock = self._get_lock(user_id)
        async with lock:
            if user_id in self._user_caches:
                return self._user_caches[user_id]

            raw = await self._read_raw(user_id)
            if raw:
                state = self._parse(raw)
            else:
                state = {"user_id": user_id, "user_name": "", "config": {}, "dates": {}}

            self._user_caches[user_id] = state
            return state

    async def save(self, user_id: int, state: Dict[str, Any]) -> None:
        lock = self._get_lock(user_id)
        async with lock:
            self._user_caches[user_id] = state
            payload = self._serialize(state)
            if self._state_msg_id is None:
                await self.init()

            prefix = "📌 Daily Target Tracker Storage ⚠️ DO NOT DELETE OR UNPIN THIS MESSAGE\n\n"
            ok = await safe_edit_message(
                self.bot, self.chat_id, self._state_msg_id,
                prefix + config.STATE_MARKER + payload,
            )
            if not ok:  # message lost (deleted/unpinned) -> recreate
                await self._recreate_state_message(payload)

    def _serialize(self, state: Dict[str, Any]) -> str:
        self._prune(state)
        payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False)
        while len(payload) > config.STATE_MAX_LEN and len(state.get("dates", {})) > 1:
            oldest = min(state["dates"])
            del state["dates"][oldest]
            payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False)

        # If still too large and we only have 1 date left, try pruning old pairs
        if len(payload) > config.STATE_MAX_LEN and len(state.get("dates", {})) == 1:
            only_date = list(state["dates"].keys())[0]
            pairs = state["dates"][only_date].get("pairs", [])
            while len(payload) > config.STATE_MAX_LEN and len(pairs) > 1:
                # remove the oldest pair to free up space
                pairs.pop(0)
                payload = json.dumps(state, separators=(",", ":"), ensure_ascii=False)

        if len(payload) > config.STATE_MAX_LEN:
            raise RuntimeError("State exceeds Telegram message size limit even after pruning.")
        return payload

    @staticmethod
    def _prune(state: Dict[str, Any]) -> None:
        # Retention window set to 30 days
        cutoff = datetime.date.today() - datetime.timedelta(days=30)
        for day in list(state.get("dates", {})):
            try:
                if datetime.date.fromisoformat(day) < cutoff:
                    del state["dates"][day]
            except ValueError:
                pass

    async def _recreate_state_message(self, payload: str) -> None:
        prefix = "📌 Daily Target Tracker Storage ⚠️ DO NOT DELETE OR UNPIN THIS MESSAGE\n\n"
        sent = await self.bot.send_message(
            self.chat_id, prefix + config.STATE_MARKER + payload,
            message_thread_id=self.thread_id,
        )
        try:
            sent = await self.bot.send_message(
                user_id, full_text,
            )
            try:
                await self.bot.pin_chat_message(
                    user_id, sent.message_id, disable_notification=True
                )
            except Exception:
                pass
            self._user_msg_ids[user_id] = sent.message_id
        except Exception as e:
            log.error("Failed to create state message for user %s: %s", user_id, e)

    # -- domain operations -------------------------------------------------- #
    async def add_tasks(self, user_id: int, date: str, specs: List[dict]) -> List[str]:
        if is_date_locked(date):
            raise ValueError(f"Targets for {date} are locked (> 48h old).")

        state = await self.load(user_id)
        day = state.setdefault("dates", {}).setdefault(
            date, {"pairs": [], "tasks": {}}
        )
        ids = []
        for spec in specs:
            task_id = new_task_id()
            task_data = {
                "label": spec["label"],
                "kind": spec.get("kind", "task"),
                "done": False,
                "score": None,
            }
            if spec.get("kind") == "questions":
                task_data["total_q"] = spec.get("total_q", 0)
                task_data["solved_q"] = spec.get("solved_q", 0)
            day["tasks"][task_id] = task_data
            ids.append(task_id)
        await self.save(user_id, state)
        return ids

    async def publish_pair(self, user_id: int, date: str, dm_chat_id: int, user_name: Optional[str] = None) -> int:
        """Post checklist to the user's linked topic AND their DM, or refresh existing message."""
        state = await self.load(user_id)
        if user_name:
            state["user_name"] = user_name
        day = state.setdefault("dates", {}).setdefault(date, {"pairs": [], "tasks": {}})

        # Determine target group and topic for this user
        cfg = state.get("config", {})
        group_id = cfg.get("group_chat_id") or config.GROUP_CHAT_ID
        topic_id = cfg.get("topic_thread_id") or config.TOPIC_THREAD_ID

        # If an active message pair already exists for today, update it in place
        if day.get("pairs"):
            pair_index = len(day["pairs"]) - 1
            updated = await self.sync_pair(user_id, date, pair_index)
            if updated:
                try:
                    await self.bot.send_message(dm_chat_id, "✅ Today's checklist updated!")
                except Exception:
                    pass
                return pair_index

        pair_index = len(day["pairs"])
        saved_name = state.get("user_name") or user_name or "Student"
        text = render_text(date, day["tasks"], user_id=user_id, user_name=saved_name)
        kb = build_keyboard(date, pair_index, day["tasks"], user_id=user_id)

        topic_msg = None
        if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
            topic_msg = await self.bot.send_message(
                config.GROUP_CHAT_ID, text,
                message_thread_id=config.TOPIC_THREAD_ID, reply_markup=kb,
            )
        dm_msg = None
        try:
            dm_msg = await self.bot.send_message(dm_chat_id, text, reply_markup=kb)
        except Exception as e:
            log.warning("Could not post to DM %s: %s", dm_chat_id, e)

        pair: Dict[str, Any] = {"dm": None, "topic": None}
        if dm_msg:
            pair["dm"] = {"chat_id": dm_msg.chat.id, "message_id": dm_msg.message_id}
        if topic_msg:
            pair["topic"] = {"chat_id": topic_msg.chat.id, "message_id": topic_msg.message_id}
        day["pairs"].append(pair)
        await self.save(user_id, state)
        return pair_index

    async def sync_pair(self, user_id: int, date: str, pair_index: int) -> bool:
        """Re-render and edit BOTH the DM and topic checklist for a user."""
        state = await self.load(user_id)
        day = state["dates"][date]
        text = render_text(date, day["tasks"])
        finished = day.get("finished", False)
        kb = build_keyboard(date, pair_index, day["tasks"], finished=finished)
        pair = day["pairs"][pair_index]
        jobs = []
        for side in ("dm", "topic"):
            target = pair.get(side)
            if target:
                jobs.append(safe_edit_message(
                    self.bot, target["chat_id"], target["message_id"], text, kb
                ))
        results = await asyncio.gather(*jobs)
        return any(results) if results else False

    async def toggle_task(self, user_id: int, date: str, pair_index: int, task_id: str) -> Optional[bool]:
        if is_date_locked(date):
            return None  # Locked

        state = await self.load(user_id)
        task = state["dates"][date]["tasks"][task_id]
        task["done"] = not task.get("done", False)
        await self.save(user_id, state)
        await self.sync_pair(user_id, date, pair_index)
        return task["done"]

    async def set_questions_solved(self, date: str, pair_index: int, task_id: str, solved: int) -> bool:
        state = await self.load()
        task = state["dates"][date]["tasks"][task_id]
        total = task.get("total_q", 0)
        task["solved_q"] = min(solved, total)
        if task["solved_q"] >= total:
            task["done"] = True
        else:
            task["done"] = False
        await self.save(state)
        await self.sync_pair(date, pair_index)
        return task["done"]

    async def set_questions_solved(self, date: str, pair_index: int, task_id: str, solved: int) -> bool:
        state = await self.load()
        task = state["dates"][date]["tasks"][task_id]
        total = task.get("total_q", 0)
        task["solved_q"] = min(solved, total)
        if task["solved_q"] >= total:
            task["done"] = True
        else:
            task["done"] = False
        await self.save(state)
        await self.sync_pair(date, pair_index)
        return task["done"]

    async def set_score(self, date: str, pair_index: int, task_id: str, score: str) -> None:
        state = await self.load()
        task = state["dates"][date]["tasks"][task_id]
        task["score"] = score
        task["done"] = True
        await self.save(user_id, state)
        await self.sync_pair(user_id, date, pair_index)
        return True

    async def finish_pair(self, user_id: int, date: str, pair_index: int) -> None:
        """Mark pair as finished, removing keyboard from both messages."""
        state = await self.load(user_id)
        day = state["dates"][date]
        user_name = state.get("user_name") or "Student"
        text = render_text(date, day["tasks"], user_id=user_id, user_name=user_name, title="🏁 Day Finished!")
        kb = build_keyboard(date, pair_index, day["tasks"], user_id=user_id, finished=True)
        pair = day["pairs"][pair_index]
        jobs = []
        for side in ("dm", "topic"):
            target = pair.get(side)
            if target:
                jobs.append(safe_edit_message(
                    self.bot, target["chat_id"], target["message_id"], text, kb
                ))
        await asyncio.gather(*jobs)

    async def delete_task(self, user_id: int, date: str, task_id: str, pair_index: int) -> bool:
        """Delete a single task and sync both messages."""
        if is_date_locked(date):
            return False

        try:
            state = await self.load(user_id)
            if date not in state.get("dates", {}):
                return False

            day = state["dates"][date]
            if task_id not in day.get("tasks", {}):
                return False

            del day["tasks"][task_id]
            if not day.get("tasks"):
                del state["dates"][date]

            await self.save(user_id, state)
            if date in state.get("dates", {}):
                await self.sync_pair(user_id, date, pair_index)
            return True
        except Exception:
            return False

    async def delete_date(self, user_id: int, date: str) -> bool:
        """Delete all targets for a specific date."""
        if is_date_locked(date):
            return False

        try:
            state = await self.load(user_id)
            if date in state.get("dates", {}):
                del state["dates"][date]
                await self.save(user_id, state)
                return True
            return False
        except Exception:
            return False