"""Ballot-builder question schema — the single source of truth for extra
(non-option) ballot fields. Choice questions stay Option rows; everything
below lives in Poll.questions as a JSON list.

Question dict shape:
    {"id": "q1", "type": "text|textarea|date|info", "label": "...",
     "help": "...", "required": true, "value": "info text"}

`id` is a stable slug (q1, q2, …) generated on save — answers are keyed by
it, so reordering questions in the builder never detaches old answers.
"""

QUESTION_TYPES = ("text", "textarea", "date", "info")

# Hard ceiling: no per-question validation beyond required/empty; answers are
# capped at 2000 chars to bound junk. ponytail: add per-type validators when
# a real ballot needs them (e.g. email format), not speculatively.
MAX_ANSWER_LEN = 2000


def validate_questions(questions):
    """Return (clean_questions, errors). Raises nothing — form-friendly."""
    errors = []
    if not questions:
        return [], errors
    if not isinstance(questions, list):
        return [], ["Questions must be a list."]
    clean = []
    seen_ids = set()
    for i, q in enumerate(questions, start=1):
        if not isinstance(q, dict):
            errors.append(f"Question {i}: must be an object.")
            continue
        qid = str(q.get("id") or f"q{i}").strip()
        qtype = str(q.get("type") or "").strip()
        label = str(q.get("label") or "").strip()
        if qtype not in QUESTION_TYPES:
            errors.append(f"Question {i}: unknown type '{qtype}'.")
            continue
        if qtype != "info" and not label:
            errors.append(f"Question {i}: label is required.")
            continue
        if qid in seen_ids:
            errors.append(f"Question {i}: duplicate id '{qid}'.")
            continue
        seen_ids.add(qid)
        clean.append(
            {
                "id": qid,
                "type": qtype,
                "label": label,
                "help": str(q.get("help") or "").strip(),
                "required": bool(q.get("required")),
                "value": str(q.get("value") or "").strip() if qtype == "info" else "",
            }
        )
    return clean, errors


def validate_answers(poll, answers):
    """Return (clean_answers, errors) for submitted text/date answers."""
    errors = []
    clean = {}
    if not poll.questions:
        return clean, errors
    if not isinstance(answers, dict):
        return clean, ["Answers must be an object."]
    for q in poll.questions:
        if q["type"] == "info":
            continue
        val = str(answers.get(q["id"]) or "").strip()
        if q["required"] and not val:
            errors.append(q["label"])
            continue
        if len(val) > MAX_ANSWER_LEN:
            errors.append(q["label"])
            continue
        if val:
            clean[q["id"]] = val
    return clean, errors