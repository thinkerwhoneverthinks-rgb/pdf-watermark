"""Telegram-as-a-database storage layer.

The whole application state lives in ONE pinned Telegram message whose body
is compact JSON prefixed with STATE_MARKER. Whenever anything changes we
re-serialize the state and edit the message in place, so the state survives
Render free-tier sleeps and redeploys (Render wipes disk, Telegram does not).
"""

import asyncio
import datetime
import json
import uuid
from typing import Any, Dict, List, Optional

from aiogram import Bot
from aiogram.exceptions import TelegramBadRequest, TelegramNotFound, TelegramRetryAfter
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

import config

MAX_EDIT_ATTEMPTS = 3


# --------------------------------------------------------------------------- #
#  Small helpers
# --------------------------------------------------------------------------- #
def new_task_id() -> str:
    return uuid.uuid4().hex[:8]


def today_str() -> str:
    return datetime.date.today().isoformat()


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
                label, cb = "📝 Enter Score", f"sc|{date}|{pair_index}|{task_id}"
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


def render_text(date: str, tasks: Dict[str, dict], title: str = "📋 Daily Targets") -> str:
    done = sum(1 for t in tasks.values() if t.get("done"))
    lines = [f"<b>{title}</b> — <code>{date}</code>", ""]
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
    """JSON state persisted inside a pinned Telegram message."""

    def __init__(self, bot: Bot):
        self.bot = bot
        self.chat_id = config.STATE_CHAT_ID
        self.thread_id = config.STATE_TOPIC_ID or None
        self._lock = asyncio.Lock()
        self._cache: Optional[Dict[str, Any]] = None
        self._state_msg_id: Optional[int] = None

    # -- lifecycle ---------------------------------------------------------- #
    async def init(self) -> None:
        raw = await self._read_raw()
        if raw is None:
            sent = await self.bot.send_message(
                self.chat_id, config.STATE_MARKER + "{}",
                message_thread_id=self.thread_id,
            )
            try:
                await self.bot.pin_chat_message(
                    self.chat_id, sent.message_id, disable_notification=True
                )
            except Exception:
                # Pinning needs admin rights in groups; state still works as
                # long as nothing else gets pinned over it.
                pass
            self._state_msg_id = sent.message_id
            raw = sent.text or config.STATE_MARKER + "{}"
        self._cache = self._parse(raw)

    async def _read_raw(self) -> Optional[str]:
        chat = await self.bot.get_chat(self.chat_id)
        pinned = getattr(chat, "pinned_message", None)
        if pinned and pinned.text and pinned.text.startswith(config.STATE_MARKER):
            self._state_msg_id = pinned.message_id
            return pinned.text
        return None

    @staticmethod
    def _parse(raw: str) -> Dict[str, Any]:
        try:
            return json.loads(raw[len(config.STATE_MARKER):])
        except Exception:
            return {"dates": {}}

    # -- read / write ------------------------------------------------------- #
    async def load(self) -> Dict[str, Any]:
        async with self._lock:
            if self._cache is None:
                raw = await self._read_raw()
                self._cache = self._parse(raw) if raw else {"dates": {}}
            return self._cache

    async def save(self, state: Dict[str, Any]) -> None:
        async with self._lock:
            self._cache = state
            payload = self._serialize(state)
            if self._state_msg_id is None:
                await self.init()
            ok = await safe_edit_message(
                self.bot, self.chat_id, self._state_msg_id,
                config.STATE_MARKER + payload,
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
        cutoff = datetime.date.today() - datetime.timedelta(days=config.STATE_RETENTION_DAYS)
        for day in list(state.get("dates", {})):
            try:
                if datetime.date.fromisoformat(day) < cutoff:
                    del state["dates"][day]
            except ValueError:
                pass

    async def _recreate_state_message(self, payload: str) -> None:
        sent = await self.bot.send_message(
            self.chat_id, config.STATE_MARKER + payload,
            message_thread_id=self.thread_id,
        )
        try:
            await self.bot.pin_chat_message(
                self.chat_id, sent.message_id, disable_notification=True
            )
        except Exception:
            pass
        self._state_msg_id = sent.message_id

    # -- domain operations -------------------------------------------------- #
    async def add_tasks(self, date: str, specs: List[dict]) -> List[str]:
        state = await self.load()
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
        await self.save(state)
        return ids

    async def publish_pair(self, date: str, dm_chat_id: int) -> int:
        """Post the checklist to the topic AND the DM, or refresh existing message."""
        state = await self.load()
        day = state["dates"][date]

        # If an active message pair already exists for today, update it in place
        if day.get("pairs"):
            pair_index = len(day["pairs"]) - 1
            updated = await self.sync_pair(date, pair_index)
            if updated:
                try:
                    await self.bot.send_message(dm_chat_id, "✅ Today's checklist updated!")
                except Exception:
                    pass
                return pair_index

        pair_index = len(day["pairs"])
        text = render_text(date, day["tasks"])
        kb = build_keyboard(date, pair_index, day["tasks"])

        topic_msg = None
        if config.GROUP_CHAT_ID and config.TOPIC_THREAD_ID:
            topic_msg = await self.bot.send_message(
                config.GROUP_CHAT_ID, text,
                message_thread_id=config.TOPIC_THREAD_ID, reply_markup=kb,
            )
        dm_msg = None
        try:
            dm_msg = await self.bot.send_message(dm_chat_id, text, reply_markup=kb)
        except Exception:
            pass

        pair: Dict[str, Any] = {"dm": None, "topic": None}
        if dm_msg:
            pair["dm"] = {"chat_id": dm_msg.chat.id, "message_id": dm_msg.message_id}
        if topic_msg:
            pair["topic"] = {"chat_id": topic_msg.chat.id, "message_id": topic_msg.message_id}
        day["pairs"].append(pair)
        await self.save(state)
        return pair_index

    async def sync_pair(self, date: str, pair_index: int) -> bool:
        """Re-render and edit BOTH the DM and the topic checklist."""
        state = await self.load()
        day = state["dates"][date]
        text = render_text(date, day["tasks"])
        kb = build_keyboard(date, pair_index, day["tasks"])
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

    async def toggle_task(self, date: str, pair_index: int, task_id: str) -> bool:
        state = await self.load()
        task = state["dates"][date]["tasks"][task_id]
        task["done"] = not task.get("done", False)
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
        await self.save(state)
        await self.sync_pair(date, pair_index)

    async def delete_task(self, date: str, task_id: str, pair_index: int) -> bool:
        """Delete a single task and sync both messages."""
        try:
            state = await self.load()
            if date not in state.get("dates", {}):
                return False
            
            day = state["dates"][date]
            if task_id not in day.get("tasks", {}):
                return False
            
            # Remove the task
            del day["tasks"][task_id]
            
            # If no tasks left, remove the date
            if not day.get("tasks"):
                del state["dates"][date]
            
            await self.save(state)
            
            # Sync the pair if date still exists
            if date in state.get("dates", {}):
                await self.sync_pair(date, pair_index)
            
            return True
        except Exception:
            return False

    async def delete_date(self, date: str) -> bool:
        """Delete all targets for a specific date."""
        try:
            state = await self.load()
            if date in state.get("dates", {}):
                del state["dates"][date]
                await self.save(state)
                return True
            return False
        except Exception:
            return False