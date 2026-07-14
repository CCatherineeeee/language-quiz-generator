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

4. Input pipeline stage 2 (ambiguity check, 2026-07-13):
   - `check_ambiguity()` + `POST /api/input/ambiguity`; verdict-only by design
     (LLM never guesses the meaning; user's answer resolves it)
   - AMBIGUITY_SYSTEM_V1: 5/5 live probe on first version (see prompt_devlog)
   - <2-candidates guard; goldens in `evals/golden/ambiguity.jsonl`; 16 tests
   - CLAUDE.md working practices added: document settled debates in
     design_choise.md; offer /grill-me after major slices

## Next up (P0 remaining, in build order)

1. **Linguistic meta-extractor**: extract `linguistic_metadata` JSON +
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

## Fable-priority list (strong-model work, do before access ends)

In value order. Items 1–2 are done (specs below). 3–6 are prompt/eval drafting —
the most model-quality-dependent work. Everything else (building slices, grilling)
works fine on Opus/Sonnet using these specs.

1. ~~Worker spec~~ (below)
2. ~~Storage transaction spec~~ (below)
3. ~~Quiz-generation prompt~~ (done 2026-07-14: mcq + translation formats,
   judged-retry loop at threshold 4, 3 live iterations — see prompt_devlog)
4. ~~Grading prompt~~ (done: deterministic fast paths, false-negative guard,
   gender-vs-accent fix — see prompt_devlog)
5. ~~Judge rubric~~ (done: substitution + sense checks; known ceiling — same-tier
   judge misses subtle flaws, run offline judge on a stronger model)
6. Meta-extractor prompt draft (also simply the next P0 slice)

Design decisions settled with these (2026-07-14): question_type mcq/translation
(worker rule: repetition >= 2 -> translation, else mcq); MCQ grading is fully
deterministic (stored explanation, correct=q4/wrong=q1, "Correct!" shows no
explanation); typed grading has an exact-match fast path; judge-retry capped at
ONE with rationale as improvement hint; sub-threshold quizzes logged
(QUIZ_JUDGE_REJECTED). P2 additions in features.md: "I guessed" honesty button,
choice-specific wrong-answer analysis, knowledge-CRUD MCP tools.

## Spec: async quiz worker

Settled by decision log #4 (Postgres queue, SKIP LOCKED). Micro-decisions below
carry their reasons; build exactly this.

- **Process model (debatable, recommendation):** v1 runs the worker as an
  asyncio background task inside the FastAPI process — one deployable service,
  one Railway bill, no IPC. Revisit to a separate process only if the worker
  ever starves the web app. Veto point for Catherine.
- **Schema additions (one Alembic migration):**
  `quiz_generation_jobs.picked_up_at` (timestamp, nullable) and
  `pending_quizzes.job_id` (FK, UNIQUE) — the unique key is what makes retries
  idempotent.
- **Loop, every ~3s:**
  1. Reap: `UPDATE quiz_generation_jobs SET status='PENDING', attempts=attempts+1
     WHERE status='PROCESSING' AND picked_up_at < now() - interval '2 minutes'`
     (2 min ≈ 4× the slowest observed LLM call; too short double-generates,
     too long delays recovery).
  2. Dead-letter: `UPDATE ... SET status='FAILED' WHERE status='PENDING' AND
     attempts >= 3` (3 tries: transient errors pass, poison jobs exit the loop).
  3. Claim: `SELECT ... WHERE status='PENDING' ORDER BY created_at LIMIT 1
     FOR UPDATE SKIP LOCKED`; set PROCESSING + picked_up_at=now(); **commit
     before the LLM call** (never hold a transaction across a network call).
  4. Generate via complete_structured (quiz schema TBD in slice 5).
  5. On success, one transaction: UPSERT pending_quizzes keyed by job_id;
     job status=DONE. On exception: attempts+1; status=PENDING if attempts<3
     else FAILED; log the error.
- **Lifecycle logs (structured JSON, one per transition):** JOB_ENQUEUED
  (producer side), JOB_PICKED_UP, JOB_DONE, JOB_FAILED, JOB_REAPED — each with
  job_id, user_id, event_type, latency_ms.
- **Tests:** two concurrent claims never grab the same job; reaper resets a
  stale PROCESSING job; attempts cap lands in FAILED; same job_id processed
  twice yields one pending_quizzes row; happy path with FakeLLM.

## Spec: storage transaction ("a new word is learned")

Runs only after user confirmation (confirm-first). Input: user_id + list of
confirmed items (token, type, language, meaning_note?, linguistic_metadata,
parent_id?). "Both meanings" = two items in the list.

One transaction, in order:

1. Per item, find-or-create `global_dictionary` row. Match key:
   (token, type, language, meaning_note) — meaning_note in the key is what
   keeps "soirée/evening" and "soirée/party" as separate rows.
2. Per created/found entity: insert `user_mastery_matrix` row **if absent**
   (PK user_id+entity_id). Initial SM-2 state: interval_days=0, ease_factor=2.5,
   repetition=0, next_review_date=now() (due immediately — a brand-new word
   should be quizzed the same day). If the row already exists, skip it and
   report "already tracked" back to the chat.
3. One `quiz_generation_jobs` insert: event_type=NEW_ITEM_ADDED,
   payload={"entity_ids": [all new ids]}, status=PENDING.
4. Commit. Any failure rolls back everything — no word without its mastery
   row, no mastery row without its quiz job.

**Tests:** failure injected after step 1 leaves zero rows; both-meanings input
creates 2 dictionary + 2 mastery rows + 1 job with both ids; re-adding a known
word adds nothing and flags "already tracked"; job payload matches created ids.

## Deferred decisions

- Hosting platform (requirement: always-on, no cold start).

## Remote

Public repo: https://github.com/CCatherineeeee/language-quiz-generator
(origin over SSH). Push after each committed slice.
