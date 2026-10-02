"""Handwritten target recognition via the Gemini Vision API."""

import asyncio
import json
import re

from aiogram import F, Router
from aiogram.types import Message, CallbackQuery
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
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

class TextParseFallback(StatesGroup):
    waiting_for_ai = State()

def _call_gemini(image_bytes: bytes) -> dict:
    """Call Gemini Vision API with better error handling."""
    try:
        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[PROMPT, genai_types.Part.from_bytes(data=image_bytes, mime_type="image/jpeg")],
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        text = response.text.strip()
        if not text:
            raise ValueError("Gemini returned empty response")
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"Invalid JSON from Gemini: {str(e)[:100]}")
    except Exception as e:
        raise ValueError(f"Gemini API error: {str(e)[:100]}")

def _extract_date_from_text(text: str) -> str | None:
    """Extract date if present in text."""
    match = re.search(r"\d{4}-\d{2}-\d{2}", text)
    if match:
        return match.group(0)
    return None

def parse_text_strict(raw_text: str) -> dict:
    """Strict pattern-based parser. No AI. Raises ValueError if can't parse."""
    text = raw_text.strip()
    if not text:
        raise ValueError("No text provided")
    
    # Extract date if present
    date = _extract_date_from_text(text) or today_str()
    
    # Split by lines and identify subject blocks
    lines = [re.sub(r"\s+", " ", ln).strip() for ln in text.splitlines() if ln.strip()]
    
    subject = None
    specs = []
    subject_pattern = r"^(CHEM|PHYSICS|BIO|BOTANY|ZOOLOGY|MATH|ENGLISH|HISTORY|GEOGRAPHY|ACCOUNTANCY|ECONOMICS)(?:ISTRY|EMATICS)?(?:\s*[:|-])?$"
    
    for line in lines:
        upper = line.upper()
        
        # Skip date lines
        if re.search(r"\d{1,2}\s+(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)", upper, re.IGNORECASE):
            continue
        
        # Detect subject
        if re.match(subject_pattern, upper):
            subject = line.strip()
            continue
        
        # Detect task (must have subject already)
        if subject and any(kw in upper for kw in ["LECTURE", "LEC", "REVISION", "REV", "QUESTION", "QUES", "NOTE", "DPP", "TEST"]):
            task = _parse_task_line_strict(line, subject)
            if task:
                specs.append(task)
    
    if not specs:
        raise ValueError("No valid targets found. Format should be:\nSUBJECT\nLECTURE/REVISION/QUESTION - details")
    
    return {"date": date, "tasks": specs}

def _parse_task_line_strict(line: str, subject: str) -> dict | None:
    """Parse a single task line strictly. Returns dict or None."""
    text = re.sub(r"\s+", " ", line).strip()
    upper = text.upper()
    
    subject_name = subject.strip() or "General"
    task_type = "Task"
    
    # Identify task type
    if "TEST" in upper:
        task_type = "TEST"
        chapter = "Test"
    elif "REVISION" in upper or "REV" in upper:
        task_type = "Revision"
        chapter = re.sub(r"(?i)(revision|rev)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "QUESTION" in upper or "QUES" in upper or "DPP" in upper:
        task_type = "Question"
        chapter = re.sub(r"(?i)(question|ques|dpp|dpp)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "LECTURE" in upper or "LEC" in upper:
        task_type = "Lecture"
        chapter = re.sub(r"(?i)(lecture|lec)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "NOTE" in upper:
        task_type = "Notes-making"
        chapter = re.sub(r"(?i)(note|notes)\s*[-:]*\s*", "", text).strip() or subject_name
    else:
        return None
    
    # Build label
    if task_type == "TEST":
        return {"label": f"TEST — {chapter} ({subject_name})", "kind": "score"}
    else:
        return {"label": f"{task_type} — {chapter} ({subject_name})"}

async def parse_text_with_ai(raw_text: str) -> dict:
    """Use Gemini AI to parse unstructured text. Fallback when strict parsing fails."""
    if _client is None:
        raise ValueError("AI parsing disabled: GEMINI_API_KEY not configured")
    
    ai_prompt = (
        "You are reading a student's study targets written in casual/messy text format.\n"
        "Extract targets into structured JSON with this schema:\n"
        '{"date": "YYYY-MM-DD", "tasks": [{"subject": "Physics", "chapter": "Thermodynamics", "type": "Lecture", "count": 1, "notes": null}]}\n'
        "Rules:\n"
        "- Use today's date if no date is mentioned.\n"
        "- type: one of Lecture, Notes-making, Revision, NCERT read, Question, or TEST\n"
        "- count: number of repetitions (e.g. '5 lectures' → count: 5)\n"
        "- Return ONLY valid JSON, no markdown, no commentary.\n\n"
        f"Text to parse:\n{raw_text}"
    )
    
    try:
        response = _client.models.generate_content(
            model=config.GEMINI_MODEL,
            contents=[ai_prompt],
            config=genai_types.GenerateContentConfig(response_mime_type="application/json"),
        )
        text = response.text.strip()
        if not text:
            raise ValueError("Gemini returned empty response")
        return json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(f"AI parsing failed: Invalid response from Gemini")

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
    except Exception as exc:
        await status.edit_text(
            f"⚠️ Could not read that photo: <code>{exc}</code>\n"
            f"Try a clearer photo."
        )


@router.message(F.text, F.chat.type == "private")
async def text_targets_import(m: Message, storage: TelegramStorage, state: FSMContext):
    """Import targets from text. Try strict parsing first, then offer AI fallback."""
    # Skip if user is in another FSM state
    current_state = await state.get_state()
    if current_state:
        return
    
    text = (m.text or "").strip()
    if not text or text.startswith("/"):
        return
    
    # Only process if looks like target text
    if not re.search(r"(?i)(lecture|revision|question|chem|physics|dpp|notes|target|lec|ques)", text):
        return
    
    status = await m.answer("🧠 Parsing your study targets…")
    
    try:
        # STEP 1: Try strict parsing
        parsed = parse_text_strict(text)
        date = parsed["date"]
        specs = parsed["tasks"]
        await storage.add_tasks(date, specs)
        await storage.publish_pair(date, m.chat.id)
        await status.edit_text(
            f"✅ Imported <b>{len(specs)}</b> target(s) for <code>{date}</code> — "
            f"check your DM and the group topic!"
        )
    except Exception as strict_error:
        # STEP 2: If strict fails, offer AI parsing
        from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup
        
        kb = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🤖 Try AI Parsing", callback_data=f"ai_parse|{m.from_user.id}")
        ]])
        
        await status.edit_text(
            f"❌ Couldn't parse strictly: <code>{str(strict_error)[:80]}</code>\n\n"
            f"Want me to use AI for better accuracy?",
            reply_markup=kb
        )
        
        # Store original text for AI parsing
        await state.set_state(TextParseFallback.waiting_for_ai)
        await state.update_data(original_text=text, user_id=m.from_user.id, status_msg_id=status.message_id)


@router.callback_query(F.data.startswith("ai_parse|"), TextParseFallback.waiting_for_ai)
async def use_ai_parsing(cb: CallbackQuery, state: FSMContext, storage: TelegramStorage):
    """Use AI to parse the text when strict parsing failed."""
    await cb.answer()
    data = await state.get_data()
    original_text = data.get("original_text", "")
    status_msg_id = data.get("status_msg_id")
    
    await cb.bot.edit_message_text(
        chat_id=cb.message.chat.id,
        message_id=status_msg_id,
        text="🤖 Using AI to understand your targets…"
    )
    
    try:
        parsed = await asyncio.to_thread(parse_text_with_ai, original_text)
        date = parsed.get("date") or today_str()
        specs = specs_from_parsed(parsed)
        
        if not specs:
            raise ValueError("AI couldn't extract any valid targets")
        
        await storage.add_tasks(date, specs)
        await storage.publish_pair(date, cb.from_user.id)
        
        await cb.bot.edit_message_text(
            chat_id=cb.message.chat.id,
            message_id=status_msg_id,
            text=f"✅ <b>AI Import Success!</b>\n\nImported <b>{len(specs)}</b> target(s) for <code>{date}</code> — "
                 f"check your DM and the group topic!"
        )
    except Exception as exc:
        await cb.bot.edit_message_text(
            chat_id=cb.message.chat.id,
            message_id=status_msg_id,
            text=f"⚠️ AI parsing also failed: <code>{str(exc)[:100]}</code>\n\n"
                 f"Try formatting like:\nSUBJECT\nLECTURE - topic\nQUESTION - details"
        )
    finally:
        await state.clear()