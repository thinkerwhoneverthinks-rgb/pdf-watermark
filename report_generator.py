"""Generates a standalone, responsive, interactive HTML study report.

Features:
- Dark / Light mode: auto-adapts to browser/device preference, plus manual ☀️/🌙 toggle.
- Sticky subject filter pill bar (All, Physics, Chemistry, Biology, Tests, Custom) with instant filtering.
- Dynamic KPI stat cards that recalculate for selected subject.
- Detailed task list grouped by date and chapter with question progress bars and score badges.
- 100% self-contained (zero external CSS/JS/fonts needed, works completely offline).
- Print / PDF friendly (@media print formatting).
"""

import html
import json
from typing import Any, Dict, List


def generate_html_report(user_id: int, user_name: str, dates_data: Dict[str, Any]) -> str:
    escaped_user_name = html.escape(user_name or "Student")

    # Sort dates descending (latest first)
    sorted_dates = sorted(dates_data.keys(), reverse=True)
    date_range_str = f"{sorted_dates[-1]} to {sorted_dates[0]}" if sorted_dates else "No activity yet"

    # Pre-calculate overall and subject-level statistics
    total_tasks = 0
    done_tasks = 0
    total_questions = 0
    solved_questions = 0
    test_scores = []
    subject_counts: Dict[str, int] = {}

    processed_days = []

    for d in sorted_dates:
        day_info = dates_data[d]
        tasks = day_info.get("tasks", {})
        day_tasks = []
        day_total = len(tasks)
        day_done = sum(1 for t in tasks.values() if t.get("done"))

        for task_id, task in tasks.items():
            label = task.get("label", "Task")
            kind = task.get("kind", "task")
            done = bool(task.get("done", False))
            score = task.get("score")
            t_q = task.get("total_q", 0)
            s_q = task.get("solved_q", 0)

            # Detect subject and chapter from label
            # Typical labels: "Lecture 1 (Physics - Thermodynamics)", "Questions (Chemistry)", "Physics", etc.
            subject = "General"
            chapter = ""

            lower_label = label.lower()
            if "physics" in lower_label or "(phy" in lower_label:
                subject = "Physics"
            elif "chemistry" in lower_label or "(chem" in lower_label:
                subject = "Chemistry"
            elif "biology" in lower_label or "(bio" in lower_label:
                subject = "Biology"
            elif "math" in lower_label:
                subject = "Maths"
            elif kind == "score" or "test" in lower_label:
                subject = "Test"

            # Extract chapter if formatted like (Chapter or Subject)
            if "(" in label and ")" in label:
                inner = label[label.rfind("(") + 1:label.rfind(")")].strip()
                if inner != subject:
                    chapter = inner

            total_tasks += 1
            if done:
                done_tasks += 1

            if kind == "questions":
                total_questions += t_q
                solved_questions += s_q

            if score:
                test_scores.append(score)

            subject_counts[subject] = subject_counts.get(subject, 0) + 1

            day_tasks.append({
                "label": label,
                "kind": kind,
                "done": done,
                "score": score,
                "total_q": t_q,
                "solved_q": s_q,
                "subject": subject,
                "chapter": chapter,
            })

        processed_days.append({
            "date": d,
            "total": day_total,
            "done": day_done,
            "tasks": day_tasks,
        })

    completion_pct = int((done_tasks / total_tasks * 100)) if total_tasks > 0 else 0
    question_pct = int((solved_questions / total_questions * 100)) if total_questions > 0 else 0

    # Build subject options
    all_subjects = sorted(list(subject_counts.keys()))
    subject_tabs_html = [
        f'<button class="filter-pill active" onclick="filterSubject(\'ALL\', this)">🌟 All ({total_tasks})</button>'
    ]
    for subj in all_subjects:
        icon = "⚡" if subj == "Physics" else ("🧪" if subj == "Chemistry" else ("🌿" if subj == "Biology" else ("📝" if subj == "Test" else "📌")))
        count = subject_counts[subj]
        subject_tabs_html.append(
            f'<button class="filter-pill" onclick="filterSubject(\'{subj}\', this)">{icon} {subj} ({count})</button>'
        )

    # Build Day cards HTML
    days_cards_html = []
    for day in processed_days:
        d_str = day["date"]
        d_done = day["done"]
        d_total = day["total"]
        pct = int((d_done / d_total * 100)) if d_total > 0 else 0
        status_class = "done" if (d_done == d_total and d_total > 0) else "partial"

        tasks_html = []
        for t in day["tasks"]:
            subj = t["subject"]
            done_mark = "✅" if t["done"] else "⏳"
            item_class = "task-item completed" if t["done"] else "task-item"

            # Detail tag
            extra_tag = ""
            if t["kind"] == "questions":
                extra_tag = f'<div class="q-progress-bar"><div class="q-fill" style="width: {int((t["solved_q"]/t["total_q"]*100) if t["total_q"]>0 else 0)}%"></div></div><span class="q-badge">{t["solved_q"]} / {t["total_q"]} Qs</span>'
            elif t["kind"] == "score" and t["score"]:
                extra_tag = f'<span class="score-badge">🏆 Scored: {html.escape(t["score"])}</span>'

            chapter_tag = f'<span class="chapter-tag">{html.escape(t["chapter"])}</span>' if t["chapter"] else ""
            subj_badge = f'<span class="subject-badge badge-{subj.lower()}">{subj}</span>'

            tasks_html.append(f'''
            <div class="{item_class}" data-subject="{subj}">
                <div class="task-left">
                    <span class="status-icon">{done_mark}</span>
                    <span class="task-title">{html.escape(t["label"])}</span>
                    {chapter_tag}
                </div>
                <div class="task-right">
                    {extra_tag}
                    {subj_badge}
                </div>
            </div>''')

        joined_tasks = "\n".join(tasks_html)
        days_cards_html.append(f'''
        <div class="day-card" data-day="{d_str}">
            <div class="day-header" onclick="toggleDay(this)">
                <div class="day-title">
                    <span class="cal-icon">🗓️</span>
                    <span class="date-text">{d_str}</span>
                    <span class="day-badge {status_class}">{d_done}/{d_total} Completed ({pct}%)</span>
                </div>
                <span class="expand-icon">▼</span>
            </div>
            <div class="day-content">
                {joined_tasks}
            </div>
        </div>''')

    joined_days = "\n".join(days_cards_html)
    subjects_json = json.dumps(subject_counts)

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{escaped_user_name} - 30-Day Study Report</title>
    <style>
        :root {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --surface-hover: #f1f5f9;
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --accent: #3b82f6;
            --accent-rgb: 59, 130, 246;
            --success: #10b981;
            --warning: #f59e0b;
            --danger: #ef4444;
            --pill-active-bg: #3b82f6;
            --pill-active-text: #ffffff;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
        }}

        @media (prefers-color-scheme: dark) {{
            :root {{
                --bg: #090d16;
                --surface: #131c2e;
                --surface-hover: #1b263b;
                --text-primary: #f8fafc;
                --text-secondary: #94a3b8;
                --border: #1e293b;
                --pill-active-bg: #3b82f6;
                --pill-active-text: #ffffff;
                --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
            }}
        }}

        [data-theme="dark"] {{
            --bg: #090d16;
            --surface: #131c2e;
            --surface-hover: #1b263b;
            --text-primary: #f8fafc;
            --text-secondary: #94a3b8;
            --border: #1e293b;
            --pill-active-bg: #3b82f6;
            --pill-active-text: #ffffff;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.3), 0 2px 4px -2px rgba(0, 0, 0, 0.2);
        }}

        [data-theme="light"] {{
            --bg: #f8fafc;
            --surface: #ffffff;
            --surface-hover: #f1f5f9;
            --text-primary: #0f172a;
            --text-secondary: #64748b;
            --border: #e2e8f0;
            --pill-active-bg: #3b82f6;
            --pill-active-text: #ffffff;
            --shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.05), 0 2px 4px -2px rgba(0, 0, 0, 0.05);
        }}

        * {{
            box-sizing: border-box;
            margin: 0;
            padding: 0;
            font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif;
            transition: background-color 0.2s ease, border-color 0.2s ease, color 0.2s ease;
        }}

        body {{
            background-color: var(--bg);
            color: var(--text-primary);
            line-height: 1.5;
            padding: 20px 16px;
            display: flex;
            justify-content: center;
        }}

        .container {{
            width: 100%;
            max-width: 900px;
        }}

        /* Header Card */
        .hero-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 16px;
            padding: 24px;
            box-shadow: var(--shadow);
            margin-bottom: 20px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            flex-wrap: wrap;
            gap: 16px;
        }}

        .hero-info h1 {{
            font-size: 24px;
            font-weight: 700;
            display: flex;
            align-items: center;
            gap: 10px;
        }}

        .hero-info p {{
            color: var(--text-secondary);
            font-size: 14px;
            margin-top: 4px;
        }}

        .theme-btn {{
            background: var(--surface-hover);
            border: 1px solid var(--border);
            color: var(--text-primary);
            padding: 8px 14px;
            border-radius: 10px;
            cursor: pointer;
            font-size: 14px;
            font-weight: 600;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        /* Metric Grid */
        .metrics-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
            gap: 14px;
            margin-bottom: 24px;
        }}

        .metric-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            padding: 16px;
            box-shadow: var(--shadow);
        }}

        .metric-title {{
            color: var(--text-secondary);
            font-size: 13px;
            font-weight: 500;
            margin-bottom: 6px;
            display: flex;
            align-items: center;
            gap: 6px;
        }}

        .metric-value {{
            font-size: 26px;
            font-weight: 800;
            color: var(--text-primary);
        }}

        .metric-sub {{
            font-size: 12px;
            color: var(--text-secondary);
            margin-top: 4px;
        }}

        /* Sticky Subject Pill Bar */
        .filter-nav-wrapper {{
            position: sticky;
            top: 10px;
            z-index: 100;
            background: var(--bg);
            padding: 6px 0 14px 0;
            margin-bottom: 10px;
        }}

        .filter-nav {{
            display: flex;
            gap: 8px;
            overflow-x: auto;
            scrollbar-width: none;
            padding-bottom: 2px;
        }}
        .filter-nav::-webkit-scrollbar {{
            display: none;
        }}

        .filter-pill {{
            background: var(--surface);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 8px 16px;
            border-radius: 20px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            white-space: nowrap;
            display: flex;
            align-items: center;
            gap: 6px;
            box-shadow: var(--shadow);
        }}

        .filter-pill:hover {{
            background: var(--surface-hover);
            color: var(--text-primary);
        }}

        .filter-pill.active {{
            background: var(--pill-active-bg);
            color: var(--pill-active-text);
            border-color: var(--pill-active-bg);
        }}

        /* Day Cards */
        .day-card {{
            background: var(--surface);
            border: 1px solid var(--border);
            border-radius: 14px;
            margin-bottom: 14px;
            overflow: hidden;
            box-shadow: var(--shadow);
        }}

        .day-header {{
            padding: 14px 18px;
            cursor: pointer;
            display: flex;
            justify-content: space-between;
            align-items: center;
            background: var(--surface);
            user-select: none;
        }}

        .day-header:hover {{
            background: var(--surface-hover);
        }}

        .day-title {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex-wrap: wrap;
        }}

        .date-text {{
            font-weight: 700;
            font-size: 15px;
        }}

        .day-badge {{
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
        }}

        .day-badge.done {{
            background: rgba(16, 185, 129, 0.15);
            color: var(--success);
        }}

        .day-badge.partial {{
            background: rgba(245, 158, 11, 0.15);
            color: var(--warning);
        }}

        .expand-icon {{
            font-size: 11px;
            color: var(--text-secondary);
            transition: transform 0.2s ease;
        }}

        .day-card.collapsed .expand-icon {{
            transform: rotate(-90deg);
        }}

        .day-card.collapsed .day-content {{
            display: none;
        }}

        /* Task Items */
        .day-content {{
            border-top: 1px solid var(--border);
            padding: 8px 14px;
        }}

        .task-item {{
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 10px 8px;
            border-radius: 8px;
            margin: 4px 0;
            gap: 12px;
            flex-wrap: wrap;
        }}

        .task-item:hover {{
            background: var(--surface-hover);
        }}

        .task-left {{
            display: flex;
            align-items: center;
            gap: 10px;
            flex: 1;
            min-width: 220px;
        }}

        .status-icon {{
            font-size: 15px;
        }}

        .task-title {{
            font-size: 14px;
            font-weight: 500;
        }}

        .chapter-tag {{
            font-size: 11px;
            background: var(--surface-hover);
            border: 1px solid var(--border);
            color: var(--text-secondary);
            padding: 2px 6px;
            border-radius: 4px;
            font-weight: 500;
        }}

        .task-right {{
            display: flex;
            align-items: center;
            gap: 8px;
        }}

        .subject-badge {{
            font-size: 11px;
            font-weight: 700;
            padding: 3px 8px;
            border-radius: 6px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}

        .badge-physics {{ background: rgba(59, 130, 246, 0.15); color: #3b82f6; }}
        .badge-chemistry {{ background: rgba(168, 85, 247, 0.15); color: #a855f7; }}
        .badge-biology {{ background: rgba(16, 185, 129, 0.15); color: #10b981; }}
        .badge-maths {{ background: rgba(245, 158, 11, 0.15); color: #f59e0b; }}
        .badge-test {{ background: rgba(239, 68, 68, 0.15); color: #ef4444; }}
        .badge-general {{ background: rgba(100, 116, 139, 0.15); color: #64748b; }}

        .q-badge {{
            font-size: 12px;
            font-weight: 700;
            color: var(--accent);
            background: rgba(var(--accent-rgb), 0.12);
            padding: 2px 7px;
            border-radius: 6px;
        }}

        .q-progress-bar {{
            width: 50px;
            height: 6px;
            background: var(--surface-hover);
            border-radius: 3px;
            overflow: hidden;
            border: 1px solid var(--border);
        }}

        .q-fill {{
            height: 100%;
            background: var(--accent);
            border-radius: 3px;
        }}

        .score-badge {{
            font-size: 12px;
            font-weight: 700;
            color: #d97706;
            background: rgba(217, 119, 6, 0.15);
            padding: 2px 8px;
            border-radius: 6px;
        }}

        .empty-filter-state {{
            display: none;
            text-align: center;
            padding: 40px;
            color: var(--text-secondary);
            font-size: 14px;
        }}

        @media print {{
            body {{
                background: #ffffff !important;
                color: #000000 !important;
            }}
            .filter-nav-wrapper, .theme-btn {{
                display: none !important;
            }}
            .day-card {{
                break-inside: avoid;
                box-shadow: none !important;
                border: 1px solid #ccc !important;
            }}
        }}
    </style>
</head>
<body>
    <div class="container">
        <!-- Hero Header -->
        <div class="hero-card">
            <div class="hero-info">
                <h1>🎯 {escaped_user_name}'s Study Report</h1>
                <p>Period: <b>{date_range_str}</b> • Standalone Interactive Report</p>
            </div>
            <button class="theme-btn" onclick="toggleTheme()">
                <span id="theme-icon">🌙</span> <span id="theme-text">Theme</span>
            </button>
        </div>

        <!-- Metric Cards Grid -->
        <div class="metrics-grid">
            <div class="metric-card">
                <div class="metric-title">🎯 Total Tasks</div>
                <div class="metric-value" id="kpi-tasks">{done_tasks} / {total_tasks}</div>
                <div class="metric-sub" id="kpi-tasks-sub">{completion_pct}% Overall Completed</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">✍️ Questions Solved</div>
                <div class="metric-value" id="kpi-questions">{solved_questions}</div>
                <div class="metric-sub" id="kpi-questions-sub">{solved_questions} of {total_questions} ({question_pct}%)</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">🗓️ Active Days</div>
                <div class="metric-value">{len(processed_days)} Days</div>
                <div class="metric-sub">Rolling 30-Day Window</div>
            </div>
            <div class="metric-card">
                <div class="metric-title">🏆 Tests Recorded</div>
                <div class="metric-value">{len(test_scores)} Tests</div>
                <div class="metric-sub">{"Best: " + test_scores[0] if test_scores else "No tests scored"}</div>
            </div>
        </div>

        <!-- Sticky Subject Filter Navigation -->
        <div class="filter-nav-wrapper">
            <div class="filter-nav">
                {"".join(subject_tabs_html)}
            </div>
        </div>

        <!-- Day Cards Container -->
        <div id="days-container">
            {joined_days}
        </div>

        <div id="empty-state" class="empty-filter-state">
            🔍 No tasks found for this subject filter.
        </div>
    </div>

    <script>
        // Theme Toggle Logic
        function toggleTheme() {{
            const current = document.documentElement.getAttribute('data-theme');
            const newTheme = current === 'dark' ? 'light' : 'dark';
            document.documentElement.setAttribute('data-theme', newTheme);
            document.getElementById('theme-icon').innerText = newTheme === 'dark' ? '☀️' : '🌙';
        }}

        // Collapse / Expand Day Card
        function toggleDay(headerElement) {{
            const card = headerElement.closest('.day-card');
            card.classList.toggle('collapsed');
        }}

        // Subject Filter Logic
        let currentFilter = 'ALL';

        function filterSubject(subject, btnElement) {{
            currentFilter = subject;

            // Highlight active button
            document.querySelectorAll('.filter-pill').forEach(b => b.classList.remove('active'));
            if (btnElement) btnElement.classList.add('active');

            let visibleDays = 0;
            let filteredTotal = 0;
            let filteredDone = 0;
            let filteredQTotal = 0;
            let filteredQSolved = 0;

            document.querySelectorAll('.day-card').forEach(dayCard => {{
                let dayHasMatchingTask = false;
                const tasks = dayCard.querySelectorAll('.task-item');

                tasks.forEach(task => {{
                    const taskSubj = task.getAttribute('data-subject');
                    if (subject === 'ALL' || taskSubj === subject) {{
                        task.style.display = 'flex';
                        dayHasMatchingTask = true;

                        filteredTotal++;
                        if (task.classList.contains('completed')) filteredDone++;
                    }} else {{
                        task.style.display = 'none';
                    }}
                }});

                if (dayHasMatchingTask) {{
                    dayCard.style.display = 'block';
                    visibleDays++;
                }} else {{
                    dayCard.style.display = 'none';
                }}
            }});

            const emptyState = document.getElementById('empty-state');
            if (visibleDays === 0) {{
                emptyState.style.display = 'block';
            }} else {{
                emptyState.style.display = 'none';
            }}

            // Dynamically update KPI card for filtered subject
            if (subject !== 'ALL') {{
                const pct = filteredTotal > 0 ? Math.round(filteredDone / filteredTotal * 100) : 0;
                document.getElementById('kpi-tasks').innerText = filteredDone + ' / ' + filteredTotal;
                document.getElementById('kpi-tasks-sub').innerText = pct + '% (' + subject + ' Only)';
            }} else {{
                document.getElementById('kpi-tasks').innerText = '{done_tasks} / {total_tasks}';
                document.getElementById('kpi-tasks-sub').innerText = '{completion_pct}% Overall Completed';
            }}
        }}
    </script>
</body>
</html>'''
