import re
from aiogram import Router, F
from aiogram.types import Message

from storage import TelegramStorage, today_str, get_relative_date_str

router = Router()

def _parse_task_line_strict(line: str, subject: str) -> dict | None:
    text = line.strip()
    if not text:
        return None

    # Check for optional time tags e.g., [till 6], [morning], [1-6], (till 6)
    time_tag = ""
    tag_match = re.search(r"[\[\(](.*?)[\]\)]$", text)
    if tag_match:
        time_tag = f" [{tag_match.group(1).strip()}]"
        text = text[:tag_match.start()].strip()
    elif "," in text:
        # Check if the text after comma looks like a time like "till 6"
        parts = text.split(",")
        last_part = parts[-1].strip().lower()
        if "till" in last_part or "morning" in last_part or "evening" in last_part or "night" in last_part or re.match(r"^\d{1,2}-\d{1,2}$", last_part):
            time_tag = f" [{parts[-1].strip()}]"
            text = ",".join(parts[:-1]).strip()

    upper = text.upper()

    # Exclude headers
    if text.isupper() and len(text) < 20 and ":" not in text and "-" not in text:
        return None

    task_type = "Task"
    chapter = subject

    # Same logic as before
    subject_name = f"({subject})" if subject else ""

    if "TEST" in upper:
        task_type = "Test"
        chapter = "Test"
    elif "REVISION" in upper or "REV" in upper:
        task_type = "Revision"
        chapter = re.sub(r"(?i)(revisions?|revs?)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "QUESTION" in upper or "QUES" in upper or "DPP" in upper:
        task_type = "Question"
        chapter = re.sub(r"(?i)(questions?|quess?|dpps?)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "LECTURE" in upper or "LEC" in upper:
        task_type = "Lecture"
        chapter = re.sub(r"(?i)(lectures?|lecs?)\s*[-:]*\s*", "", text).strip() or subject_name
    elif "NOTE" in upper:
        task_type = "Notes-making"
        chapter = re.sub(r"(?i)(notes?)\s*[-:]*\s*", "", text).strip() or subject_name
    else:
        return None

    # Build spec based on task type
    if task_type == "Question":
        matches = re.findall(r'\d+', line)
        count = sum([int(m) for m in matches]) if matches else 50 # dummy default
        return {
            "label": f"{task_type} - {chapter}{time_tag}",
            "kind": "questions",
            "total_q": count,
            "solved_q": 0
        }
    elif task_type == "Lecture":
        matches = re.findall(r'\d+', line)
        count = int(matches[-1]) if matches else 1
        specs = []
        for i in range(1, count + 1):
             specs.append({
                 "label": f"{task_type} {i} - {chapter}{time_tag}",
                 "kind": "task"
             })
        return specs # Return a list of specs for lectures
    else:
        return {
            "label": f"{task_type} - {chapter}{time_tag}",
            "kind": "task"
        }

@router.message(F.text, F.chat.type == "private")
async def handle_text_targets(m: Message, storage: TelegramStorage):
    if m.text.startswith("/"):
        return # Ignore commands

    lines = m.text.split("\n")
    specs = []
    current_subject = ""

    # Check if the first line is a date specifier
    date_to_use = today_str()
    first_line_lower = lines[0].strip().lower()
    if first_line_lower in ["today", "tmrw", "tomorrow", "day after tomorrow", "next 2 days"]:
        if "after tomorrow" in first_line_lower:
            date_to_use = get_relative_date_str(2)
        elif "tmrw" in first_line_lower or "tomorrow" in first_line_lower:
            date_to_use = get_relative_date_str(1)
        # remove date line
        lines = lines[1:]
    elif "day 1" in first_line_lower: # just as fallback
        lines = lines[1:]

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Detect subjects (all caps, short)
        if line.isupper() and len(line) < 20 and ":" not in line and "-" not in line:
            if "CHEM" in line:
                current_subject = "Chemistry"
            elif "PHY" in line:
                current_subject = "Physics"
            elif "BIO" in line:
                current_subject = "Biology"
            elif "MATH" in line:
                current_subject = "Maths"
            else:
                current_subject = line.title()
            continue

        spec_or_specs = _parse_task_line_strict(line, current_subject)
        if spec_or_specs:
            if isinstance(spec_or_specs, list):
                specs.extend(spec_or_specs)
            else:
                specs.append(spec_or_specs)

    if specs:
        await storage.add_tasks(date_to_use, specs)
        await storage.publish_pair(date_to_use, m.chat.id)
    else:
        await m.answer("I couldn't understand any targets from that text. Try using /q or the UI!")
