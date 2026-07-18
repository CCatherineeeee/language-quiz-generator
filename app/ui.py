"""Gradio chat UI (features.md P0) — walks the planning.md input-to-quiz flow.

Two layers on purpose:
- chat_step(): the whole Learn-tab conversation as a plain function
  (message + state in -> reply + new state out). No Gradio in it, so tests
  drive every branch with a FakeLLM and never render a UI.
- build_ui(): thin Gradio wiring. Components in, chat_step out.

The state dict's "step" field is the conversation position:
  idle -> confirm_correction -> resolve_ambiguity -> confirm_save -> idle
(each stage can be skipped when the check passes clean — see planning.md).
"""

from dataclasses import dataclass

import gradio as gr
from sqlalchemy import select

from app.db import SessionLocal
from app.models import PendingQuiz, QuizStatus
from app.services.analysis import check_ambiguity, check_input
from app.services.extraction import ExtractionResult, extract_knowledge
from app.services.review import SubmittedAnswer, submit_quiz
from app.services.storage import ConfirmedItem, DanglingParentError, store_confirmed_items

USERS = {"Catherine": 1, "Demo": 2}


# ---------------------------------------------------------------- Learn tab

@dataclass
class ChatDeps:
    """Injection point: tests swap in a FakeLLM and a SQLite session factory."""

    session_factory: object = SessionLocal
    client: object = None  # None -> each service builds the real LLMClient


def _numbered(lines: list[str]) -> str:
    return "\n".join(f"{i + 1}. {line}" for i, line in enumerate(lines))


def _describe_extraction(result: ExtractionResult) -> str:
    items = _numbered(
        [
            f"**{it.token}** ({it.type}"
            + (f", parent: {it.parent_token}" if it.parent_token else "")
            + (f") — {it.meaning_note}" if it.meaning_note else ")")
            for it in result.items
        ]
    )
    reply = f"Here is what I'll save:\n{items}"
    if result.suggestions:
        sugg = _numbered(
            [f"{s.token} ({s.relation})" for s in result.suggestions]
        )
        reply += (
            f"\n\nRelated forms you could learn too:\n{sugg}"
            "\n\nSave? **yes** / **yes+1,3** (to include those suggestions)"
            " / **no**"
        )
    else:
        reply += "\n\nSave? **yes** / **no**"
    return reply


def _extract(text: str, resolved: str | None, state: dict, deps: ChatDeps) -> str:
    result = extract_knowledge(text, resolved_meaning=resolved, client=deps.client)
    if not result.items:
        state.clear()
        return "I couldn't find anything to learn in that — try rephrasing?"
    state.clear()
    state.update(
        step="confirm_save",
        items=[it.model_dump() for it in result.items],
        suggestions=[s.model_dump() for s in result.suggestions],
    )
    return _describe_extraction(result)


def _after_text_settled(text: str, state: dict, deps: ChatDeps) -> str:
    """Stage 2 (ambiguity), then stage 3 (extraction)."""
    amb = check_ambiguity(text, client=deps.client)
    if amb.is_ambiguous:
        state.clear()
        state.update(step="resolve_ambiguity", text=text)
        if amb.clarification_question:
            return amb.clarification_question
        options = " / ".join(c.meaning for c in amb.candidates)
        return f"Quick check — which meaning do you intend: {options}? (or: both)"
    return _extract(text, None, state, deps)


def _handle_idle(message: str, state: dict, deps: ChatDeps) -> str:
    checked = check_input(message, client=deps.client)
    if checked.has_issues:
        fixes = _numbered(
            [f"{i.original} -> {i.corrected} ({i.explanation})" for i in checked.issues]
        )
        state.clear()
        state.update(
            step="confirm_correction",
            original=message,
            corrected=checked.corrected_input,
        )
        return (
            f"Before we continue, I spotted:\n{fixes}\n\n"
            f'Use the corrected version — "{checked.corrected_input}"? '
            "**yes** / **no** (keep my original)"
        )
    return _after_text_settled(message, state, deps)


def _parse_save_reply(message: str, n_suggestions: int) -> tuple[bool, list[int]] | None:
    """'yes' -> (True, []); 'yes+1,3' -> (True, [0, 2]); 'no' -> (False, []).
    None means unparseable — re-ask."""
    reply = message.strip().lower().replace(" ", "")
    if reply in ("no", "n", "non"):
        return (False, [])
    if reply in ("yes", "y", "oui"):
        return (True, [])
    if reply.startswith("yes+"):
        try:
            picks = [int(p) - 1 for p in reply.removeprefix("yes+").split(",")]
        except ValueError:
            return None
        if all(0 <= p < n_suggestions for p in picks):
            return (True, picks)
    return None


def _handle_confirm_save(message: str, state: dict, deps: ChatDeps) -> str:
    parsed = _parse_save_reply(message, len(state.get("suggestions", [])))
    if parsed is None:
        return "Please answer **yes**, **yes+1,3** (suggestion numbers), or **no**."
    save, picks = parsed
    if not save:
        state.clear()
        return "Discarded — nothing saved. What else did you learn?"

    items = [ConfirmedItem(**it) for it in state["items"]]
    for p in picks:
        s = state["suggestions"][p]
        items.append(
            ConfirmedItem(token=s["token"], type=s["type"], parent_token=s["parent_token"])
        )
    user_id = state["user_id"]
    state.clear()
    try:
        with deps.session_factory() as session:
            result = store_confirmed_items(session, user_id, items)
    except DanglingParentError:
        return (
            "Something went wrong linking a word to its base form, so nothing "
            "was saved. Please try rephrasing what you learned."
        )
    reply = ""
    if result.stored:
        saved = ", ".join(s.token for s in result.stored)
        reply = f"Saved: **{saved}**. A quiz is being prepared — check the Quiz tab soon!"
    if result.already_tracked:
        known = ", ".join(result.already_tracked)
        reply += f"\n(Already in your review schedule: {known}.)"
    return reply.strip() or "Nothing new to save."


def chat_step(message: str, state: dict, user_id: int, deps: ChatDeps) -> str:
    """One conversation turn. Mutates state; returns the assistant reply."""
    message = message.strip()
    if not message:
        return "Tell me what you learned today!"
    if len(message) > 2000:
        return "That's a lot at once! Please keep it under 2000 characters."
    state["user_id"] = user_id

    step = state.get("step", "idle")
    if step == "confirm_correction":
        reply = message.lower().strip()
        original, corrected = state["original"], state["corrected"]
        if reply in ("yes", "y", "oui"):
            return _after_text_settled(corrected, state, deps)
        if reply in ("no", "n", "non"):
            return _after_text_settled(original, state, deps)
        return 'Please answer **yes** (use correction) or **no** (keep original).'
    if step == "resolve_ambiguity":
        return _extract(state["text"], message, state, deps)
    if step == "confirm_save":
        return _handle_confirm_save(message, state, deps)
    return _handle_idle(message, state, deps)


# ----------------------------------------------------------------- Quiz tab

def fetch_open_quizzes(user_id: int, session_factory=SessionLocal) -> list[dict]:
    """ALL unanswered quizzes (decision 2026-07-18: not just the oldest)."""
    with session_factory() as session:
        quizzes = session.scalars(
            select(PendingQuiz)
            .where(
                PendingQuiz.user_id == user_id,
                PendingQuiz.status == QuizStatus.PENDING,
            )
            .order_by(PendingQuiz.created_at)
        ).all()
        return [
            {"quiz_id": q.id, "questions": q.quiz_data["questions"]} for q in quizzes
        ]


def answers_from_values(questions: list[dict], values: list) -> list[SubmittedAnswer]:
    """Map raw Gradio component values (radio choice text / typed text) to
    the submit schema. Unanswered questions raise so nothing half-graded."""
    answers = []
    for q, value in zip(questions, values, strict=True):
        question = q["question"]
        if value in (None, ""):
            raise ValueError("Please answer every question before submitting.")
        if question["question_type"] == "mcq":
            answers.append(
                SubmittedAnswer(chosen_index=question["choices"].index(value))
            )
        else:
            answers.append(SubmittedAnswer(typed_answer=value))
    return answers


def _submit_one_quiz(quiz: dict, values: list, session_factory=SessionLocal) -> str:
    try:
        answers = answers_from_values(quiz["questions"], list(values))
    except ValueError as exc:
        return str(exc)
    with session_factory() as session:
        result = submit_quiz(session, quiz["quiz_id"], answers)
    lines = []
    for out in result.outcomes:
        mark = "✅" if out.is_correct else "❌"
        lines.append(
            f"{mark} {out.feedback}  \n"
            f"→ next review in {out.interval_days} day(s) "
            f"({out.next_review_date.date()})"
        )
    return "\n\n".join(lines)


# ------------------------------------------------------------------ wiring

def build_ui() -> gr.Blocks:
    with gr.Blocks(title="Language Quiz Generator") as demo:
        gr.Markdown("# Language Quiz Generator")
        user_dd = gr.Dropdown(
            choices=list(USERS), value="Catherine", label="Account"
        )

        with gr.Tab("Learn"):
            chatbot = gr.Chatbot(height=420)
            msg_box = gr.Textbox(
                placeholder="Tell me what you learned today…", show_label=False
            )
            chat_state = gr.State({})

            def on_message(message, history, state, user_name):
                deps = ChatDeps()
                reply = chat_step(message, state, USERS[user_name], deps)
                history = history + [
                    {"role": "user", "content": message},
                    {"role": "assistant", "content": reply},
                ]
                return history, state, ""

            msg_box.submit(
                on_message,
                inputs=[msg_box, chatbot, chat_state, user_dd],
                outputs=[chatbot, chat_state, msg_box],
            )

        with gr.Tab("Quiz"):
            fetch_btn = gr.Button("Get my quizzes")
            quizzes_state = gr.State([])

            def on_fetch(user_name):
                return fetch_open_quizzes(USERS[user_name])

            fetch_btn.click(on_fetch, inputs=[user_dd], outputs=[quizzes_state])

            @gr.render(inputs=quizzes_state)
            def render_quizzes(quizzes):
                if not quizzes:
                    gr.Markdown("No quizzes waiting — go learn something!")
                    return
                for quiz in quizzes:
                    gr.Markdown(f"### Quiz #{quiz['quiz_id']}")
                    components = []
                    for q in quiz["questions"]:
                        question = q["question"]
                        if question["question_type"] == "mcq":
                            components.append(
                                gr.Radio(
                                    choices=question["choices"],
                                    label=question["prompt_text"],
                                )
                            )
                        else:
                            components.append(
                                gr.Textbox(label=question["prompt_text"])
                            )
                    feedback = gr.Markdown()
                    submit = gr.Button(f"Submit quiz #{quiz['quiz_id']}")

                    def on_submit(*values, _quiz=quiz):
                        return _submit_one_quiz(_quiz, values)

                    submit.click(on_submit, inputs=components, outputs=[feedback])

    return demo
