"""The per-application brief: the prompt Claude Code gets, and the shape of what it reports."""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

WORKDAY_JS = Path(__file__).with_name("workday_fill.js")

STATUSES = ("submitted", "ready-to-submit", "needs-you", "failed")

RESULT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": list(STATUSES)},
        "needs_you_reason": {"type": "string"},
        "pending_questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "question": {"type": "string"},
                    "type": {"type": "string"},
                    "options": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["question"],
            },
        },
        "answers_used": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"question": {"type": "string"}, "answer": {"type": "string"}},
                "required": ["question", "answer"],
            },
        },
        "confirmation_text": {"type": "string"},
        "notes": {"type": "string"},
        "form_lessons": {"type": "array", "items": {"type": "string"}, "maxItems": 5},
    },
    "required": ["status"],
}

# Phrases that carry no information. A free-text answer written for a posting avoids them.
STOCK_PHRASES = [
    "innovative", "cutting-edge", "state-of-the-art", "world-class", "industry-leading",
    "market leader", "your mission", "your culture", "your values", "passionate about",
    "I have long admired", "I have been a fan of", "I am excited to join",
    "I am excited about the opportunity", "great place to work", "perfect fit",
    "perfect match", "as a leader in", "I am writing to apply",
]


def is_workday(posting: dict) -> bool:
    url = " ".join(str(posting.get(k) or "") for k in ("apply_url", "url")).lower()
    return (posting.get("ats") or "").lower() == "workday" or "myworkdayjobs.com" in url \
        or "myworkdaysite.com" in url


def _email_code_rule(tool: bool) -> str:
    """What to do when, after Submit, the form asks for a code emailed to the person."""
    head = ("- A security code EMAILED to the person to finish this application (the form asks for\n"
            "  it after Submit) is not a CAPTCHA. ")
    if tool:
        return head + (
            "Call wait_for_email_code, type the code it returns into the\n"
            "  code box, and submit again. If it returns no code, leave the tab on the code box and\n"
            "  report needs-you with the reason 'Enter the code emailed to you in the open tab, then\n"
            "  submit.' Never use it for a sign-in or account code.\n")
    return head + (
        "Leave the tab on the code box and report needs-you with the\n"
        "  reason 'Enter the code emailed to you in the open tab, then submit. Connect your email\n"
        "  in Settings and applyfirst enters these codes itself.'\n")


def _own_window(browser: str) -> bool:
    """The applyfirst window runs on Playwright MCP; "playwright" is its old name."""
    return browser in ("own-window", "playwright")


def _js_tool(browser: str) -> str:
    return "browser_evaluate" if _own_window(browser) else "javascript_tool"


def _mode_rules(mode: str) -> str:
    if mode == "auto":
        return (
            "MODE: auto. Fill every field, then submit the application yourself. After the final\n"
            "submit, wait for the confirmation page or message and copy its text into\n"
            "confirmation_text. Submitted is only true when you saw a confirmation on the page;\n"
            "if you clicked submit and saw none, report needs-you and say so. Close the tab you\n"
            "opened once the application is submitted, and close it too if you report failed.\n"
            "If you report needs-you, leave the form tab open where you stopped so the person can\n"
            "finish it there."
        )
    return (
        "MODE: review. Fill every field and attach the files, then STOP. Do not click the final\n"
        "submit button (Submit, Submit Application, Send Application, or the last button of the\n"
        "form), and do not press Enter inside the form. Leave the tab open on the finished form\n"
        "so the person can read it and press submit themselves, and report ready-to-submit.\n"
        "If you report needs-you, leave the form tab open where you stopped. If you report failed,\n"
        "close it."
    )


def _workday_section(workday_answers: dict, browser: str) -> str:
    tool = _js_tool(browser)
    if _own_window(browser):
        how = (f"2. On each step of the application make ONE {tool} call whose function is\n"
               "   `async () => { <the whole file content>; return await wdFill(ANSWERS); }`\n"
               "   where ANSWERS is this object:\n")
    else:
        how = (f"2. On each step of the application make ONE {tool} call: the whole file content, then\n"
               "   `; await wdFill(ANSWERS)` where ANSWERS is this object:\n")
    return (
        "WORKDAY: this form runs on Workday. Do not fill it click by click.\n"
        f"1. Read the script at {WORKDAY_JS} (read it with an explicit line limit).\n"
        + how +
        f"{json.dumps(workday_answers, indent=2, ensure_ascii=False)}\n"
        "3. The call returns {filled, unmatched, consent, errors}. Fix every required\n"
        "   `unmatched` field and every `errors` entry by hand (use the standard answers, learned\n"
        "   answers and rules below). Read text fields back from the page, since the script has\n"
        "   reported fields filled that the page then rejected. Keep each call to a few fields; a\n"
        "   call that opens many dropdowns can freeze the page.\n"
        "4. The script never checks consent boxes and never clicks Save and Continue. Tick the\n"
        "   required consent box yourself where the form refuses to continue without it, then\n"
        "   click Save and Continue, and re-read the step name to confirm the page moved on.\n"
        "5. Upload the resume yourself with the file upload tool; the script lists file inputs in\n"
        "   `unmatched`. Re-inject the script on every new step (helpers are lost on reload)."
    )


def build_brief(
    posting: dict,
    *,
    mode: str,
    resume_path: str,
    cover_letter_path: str | None,
    cover_letters_setting: str,
    standard: dict,
    learned: list[dict],
    experience: list[str],
    settings_apply: dict,
    browser: str,
    workday: dict | None = None,
    form_notes: str = "",
    email_code_tool: bool = False,
) -> str:
    desc = (posting.get("description") or "").strip()
    apply_url = posting.get("apply_url") or posting.get("url") or ""
    pace = settings_apply.get("pace_seconds", 3)

    if cover_letter_path:
        cover = f"Cover letter file (upload it where the form takes a cover letter): {cover_letter_path}"
    elif cover_letters_setting == "never":
        cover = "No cover letter: leave optional cover letter fields empty."
    else:
        cover = ("No cover letter file exists. If the form REQUIRES a cover letter, stop and report "
                 "needs-you with the reason 'cover letter required'. Leave optional ones empty.")

    if standard["commitments"]["policy"] == "yes":
        commit = (
            "Forward-looking commitment questions (willing to relocate, travel, work onsite or\n"
            "hybrid, shifts, overtime, available on the start date, scheduled for a work term):\n"
            "answer Yes. Present or past facts (degree, enrolment, citizenship, licences,\n"
            "prior employment) are answered literally from the profile."
        )
    else:
        commit = (
            "Forward-looking commitment questions (relocation, travel, onsite, shifts, start date):\n"
            "answer literally from the profile. If the profile does not say, it is a pending\n"
            "question; do not guess."
        )

    learned_lines = "\n".join(f"- {a['question']} => {a['answer']}" for a in learned) or "(none yet)"
    exp_lines = "\n".join(f"- {line}" for line in experience) or "(none on file)"
    stock = ", ".join(f'"{p}"' for p in STOCK_PHRASES)

    parts = [
        "You are filling out one job application in the browser for the person whose details\n"
        "follow. Work on this one application only, in a single tab.",
        f"POSTING\nCompany: {posting.get('company', '')}\nTitle: {posting.get('title', '')}\n"
        f"Location: {posting.get('location', '')}\nPosting page: {posting.get('url', '')}\n"
        f"Application form: {apply_url}\nSource: {posting.get('source', '')}"
        + (f"\nDeadline: {posting['deadline']}" if posting.get("deadline") else "")
        + (f"\n\nPosting text:\n{desc[:6000]}" if desc else "\n\n(The posting text was not retrieved.)"),
        _mode_rules(mode),
        f"FILES\nResume (upload this exact file, under this file name): {resume_path}\n{cover}",
        "STANDARD ANSWERS (from the person's profile; use these values exactly)\n"
        + json.dumps(standard, indent=2, ensure_ascii=False),
        "LEARNED ANSWERS (questions answered on earlier applications; use them when a form asks\n"
        "the same thing in other words)\n" + learned_lines,
        "RULES FOR ANSWERS\n"
        f"- {commit.replace(chr(10), chr(10) + '  ')}\n"
        "- Work authorization and sponsorship: use the country the question names. Where the\n"
        "  question names no country, use the posting's country. If the profile has no entry for\n"
        "  that country, it is a pending question.\n"
        "- Salary: use the salary figure in the standard answers, in the unit the field asks for.\n"
        "- Demographic and voluntary self-identification questions: use the value given; an empty\n"
        "  value means choose the decline / prefer-not-to-say option.\n"
        "- How did you hear about us: use the value given, or the closest true option. Never pick\n"
        "  employee referral or alumni.\n"
        "- Consent to marketing messages: decline. Consent needed to process this application or\n"
        "  to accept the site's terms: give it.\n"
        "- A question with a learned answer or a standard answer is answered from it. Never invent\n"
        "  a value for a personal fact.\n"
        "- Free-text questions about this company or role (why us, why you): write them from the\n"
        "  posting's actual work plus one or two concrete facts about the person from the\n"
        "  experience list below, with exact numbers when the experience line has one. Claim\n"
        "  nothing that is not in the list. Avoid stock phrases: " + stock + ". No hedged numbers\n"
        "  (about, roughly, nearly).",
        "EXPERIENCE ON FILE (the only claims you may make about the person in free text)\n" + exp_lines,
        _workday_section(workday, browser) if workday is not None else
        "FORM TIPS\n"
        "- Plain text fields: fill them in one batch. Comboboxes and dropdowns often ignore a typed\n"
        "  value: click the field, type the first letters, wait for the option list, click the option.\n"
        "- A hidden or shadow-DOM file input: create a temporary visible file input in the page,\n"
        "  upload to it, then move its file into the real input with a DataTransfer and dispatch a\n"
        "  change event on the real input.\n"
        "- Skip any 'autofill from resume' uploader; it overwrites fields you already set.",
        *([form_notes] if form_notes else []),
        "WORKING RULES\n"
        "- Never press Enter inside a form and never reload or navigate a tab that holds filled\n"
        "  state; both lose the fields. Click buttons instead.\n"
        f"- Leave at least {pace} seconds between page loads on the same site.\n"
        "- READ EVERYTHING BACK. A tool saying it set a field is not evidence that the page holds\n"
        "  the value. After filling, read each field's value off the page (or a screenshot) and\n"
        "  fix any that did not take, before you report anything as filled.\n"
        "- Before the last step, read the whole review page back: name, email, phone, resume file\n"
        "  name, start date, work authorization.\n"
        "- Sign-in walls: if the form needs an account you are not already signed in to, or asks to\n"
        "  create one, stop. Do not create accounts, type passwords or use reset flows. Report\n"
        "  needs-you with the reason, for example 'sign-in needed: <site>'.\n"
        "- CAPTCHAs and bot checks: stop and report needs-you, for example 'CAPTCHA on <site>'.\n"
        + (_email_code_rule(email_code_tool) if mode == "auto" else "") +
        "- A REQUIRED question that has no standard answer and no learned answer: do not guess and\n"
        "  do not leave it blank. Collect every such question on the form, fill everything else,\n"
        "  and report needs-you with each question in pending_questions: the exact question text,\n"
        "  its type (text, textarea, select, radio, checkbox, date, file) and its options if it has\n"
        "  a fixed list.\n"
        "- If the posting is closed, the form is broken, or you cannot continue for another reason,\n"
        "  report failed with the reason in notes. Say what happened in plain words.",
        "REPORT\n"
        "Finish with the structured result: status (submitted | ready-to-submit | needs-you |\n"
        "failed), needs_you_reason (plain words, when needs-you), pending_questions,\n"
        "answers_used (every question you answered with a learned answer or an answer you wrote,\n"
        "with the exact text you entered), confirmation_text (the confirmation text copied off the\n"
        "page, when submitted), notes (anything the person should know, in plain words),\n"
        "form_lessons (up to 5 short notes, one sentence each, on how THIS KIND OF FORM behaves,\n"
        "for the next application on the same form system: a widget that ignored typing, an\n"
        "upload that needed a workaround, a button that moved, what finally worked. Only the\n"
        "form's mechanics: no company or person names, no links, no answers, nothing copied from\n"
        "the page. Leave it empty when nothing was learned).",
    ]
    return "\n\n".join(parts) + "\n"
