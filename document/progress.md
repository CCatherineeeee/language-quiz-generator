# Progress

Living status doc. Update the "Done" and "Next up" sections at the end of every
working session so the next session can resume without archaeology.

## Done (as of 2026-07-10)

Commits on `main` (no remote yet):

1. `3b61521` — design docs, decision log, demo prototype committed.
2. `af49888` — project skeleton:
   - uv + pyproject.toml + uv.lock, Python pinned 3.12, ruff + pytest configured
   - `app/models.py`: all 5 tables from planning.md (note: `interval` is
     `interval_days` in code — INTERVAL is a Postgres keyword)
   - Alembic wired to `.env` settings; `include_object` guard so the shared
     Neon DB's `demo_*` tables are never dropped (autogenerate tried to!)
   - Migration `b32919fbbea3` applied to Neon; users seeded: 1=Catherine(owner),
     2=Demo(is_demo)
   - `app/llm/`: fallback chain (Groq -> Gemini -> OpenRouter) +
     `complete_structured()` (Pydantic-validated output, one repair retry)
3. `005d182` — input pipeline stage 1 (spelling & grammar check):
   - `check_input()` in `app/services/analysis.py`; confirm-first (reports
     corrections, never silently rewrites; chat layer will ask user to confirm)
   - `POST /api/input/check` with 413 guardrail at 2000 chars
   - Prompt V2 live (V1 missed an accent typo — see prompt_devlog.md);
     no-op issues filtered in code
   - First 4 golden cases: `evals/golden/input_check.jsonl`

Verified working: 12 tests pass, ruff clean, `/health/db` reaches Neon,
live LLM probe through Groq succeeds.

## Conventions

- Run things: `uv run pytest -q`, `uv run ruff check app tests`,
  `uv run uvicorn app.main:app`, `uv run alembic upgrade head`
- Prompts: versioned constants in `app/prompts.py` (`*_V1`, `*_V2`, never edit
  a shipped version); every bump logged in `document/prompt_devlog.md`; live
  failures become golden cases in `evals/golden/`
- Schema changes: edit models -> `uv run alembic revision --autogenerate -m ...`
  -> hand-review the script (mandatory) -> `uv run alembic upgrade head`
- Commit per working slice; messages explain the why.

## Next up (P0 remaining, in build order)

1. **Ambiguity check** (Analysis Layer stage 2): `is_ambiguous` +
   clarification short-circuit (soirée: evening vs party). Same pattern as
   stage 1: Pydantic schema + versioned prompt + live probe + golden cases.
2. **Linguistic meta-extractor**: extract `linguistic_metadata` JSON +
   related-form suggestions (conjugations, plural, gender).
3. **Storage flow** ("A New Word is Learned", planning.md): write
   global_dictionary + user_mastery_matrix rows; enqueue NEW_ITEM_ADDED job in
   the same transaction.
4. **Queue worker**: poll quiz_generation_jobs with FOR UPDATE SKIP LOCKED;
   retries + attempts; event lifecycle logging.
5. **Quiz generation** prompt + write to pending_quizzes.
6. **Grading + SM-2 update** (SM-2 as pure function behind a scheduler
   interface, unit-tested).
7. **Daily due sweep** (USER_ITEMS_DUE producer) + demo-account nightly reset.
8. **Gradio chat UI** mounted on FastAPI, wiring the pipeline end to end.
9. Owner login (env-var secret cookie), then deploy (platform still TBD).

## Deferred decisions

- Hosting platform (requirement: always-on, no cold start).
- GitHub remote not created yet; everything is local.
