"""Handwritten target recognition via the Gemini Vision API."""

import asyncio
import json
import re

from aiogram import F, Router
from aiogram.types import Message
from google import genai
from google.genai import types as genai_types

import config
from storage import TelegramStorage, today_str

router = Router()

_client = genai.Client(api_key=config.GEMINI_API_KEY) if config.GEMINI_API_KEY else None

PROMPT = (
    "You are reading a photo of a student's handwritten daily study targets. "
    "Extract every target into structured JSON with EXACTLY this schema:\n"
    '{\n  "date": "YYYY-MM-DD",\n  "tasks": [\n    {\n      "subject": "Physics",\n'
    '      "chapter": "Thermodynamics",\n      "type": "Lecture",\n      "count": 3,\n'
    '      "notes": "Carnot engine focus",\n      "score": null\n    }\n  ]\n}\n'
    "Rules:\n"
    "- Use today's date if no date is written.\n"
    "- count is the number of identical repetitions (lectures, pages, questions); default 1.\n"
    "- type is one of: Lecture, Notes-making, Revision, NCERT read, TEST, or a short custom type.\n"
    "- If the target is a test/exam, set type to TEST.\n"
    "- score is always null unless a score is explicitly written.\n"
    "- notes is a short string or null.\n"
    "- Return ONLY the JSON, no markdown fences, no commentary."
)


def _call_gemini(image_bytes: bytes) -> dict:
    response = _client.models.generate_content(
        model=config.GEMINI_MODEL,
        contents=[PROMPT, genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
        config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
    )
    return json.loads(response.text)


def specs_from_parsed(parsed: dict) -> list:
    specs = []
    for item in parsed.get("tasks", []):
        subject = str(item.get("subject") or "General").strip()
        chapter = str(item.get("chapter") or "").strip()
        ttype = str(item.get("type") or "Task").strip()
        note = (item.get("notes") or "").strip()
        try:
            count = max(1, min(50, int(item.get("count") or 1)))
        except (TypeError, ValueError):
            count = 1

        if ttype.upper() == "TEST" or subject.upper() == "TEST":
            specs.append({"label": f"TEST — {chapter or subject}", "kind": "score"})
            continue

        if count > 1:
            for i in range(1, count + 1):
                text = f"{ttype} {i} — {chapter} ({subject})"
                specs.append({"label": f"{text} · {note}" if note else text})
        else:
            text = f"{ttype} — {chapter} ({subject})"
            specs.append({"label": f"{text} · {note}" if note else text})
    return specs


@router.message(F.photo, F.chat.type == "private")
async def vision_import(m: Message, storage: TelegramStorage):
    if _client is None:
        return await m.answer("⚠️ Vision is disabled: GEMINI_API_KEY is not configured.")
    status = await m.answer("🔍 Reading your handwritten targets…")
    try:
        file = await m.bot.get_file(m.photo[-1].file_id)
        buffer = await m.bot.download_file(file.file_path)
        image_bytes = buffer.read()
        parsed = await asyncio.to_thread(_call_gemini, image_bytes)

        raw_date = str(parsed.get("date") or "")
        date = raw_date if re.fullmatch(r"\d{4}-\d{2}-\d{2}", raw_date) else today_str()

        specs = specs_from_parsed(parsed)
        if not specs:
            raise ValueError("no tasks recognised")
        await storage.add_tasks(date, specs)
        await storage.publish_pair(date, m.chat.id)
        await status.edit_text(
            f"✅ Imported <b>{len(specs)}</b> task(s) for <code>{date}</code> — "
            f"check your DM and the group topic!"
        )
    except Exception as exc:  # Gemini / network / parse failures
        await status.edit_text(
            f"⚠️ Could not read that photo: <code>{exc}</code>\nTry a clearer photo."
        )
