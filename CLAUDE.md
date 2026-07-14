# Language Quiz Generator

Resume portfolio project (targets: AI engineer and backend engineer roles). An LLM-powered language-learning app: users report what they learned in chat, the app extracts structured linguistic knowledge, schedules it with SM-2 spaced repetition, and generates personalized quizzes via an async worker.

## Read before implementing

1. [document/progress.md](document/progress.md) — **current status, conventions, and what to build next. Start here, and update it at the end of every session.**
2. [document/features.md](document/features.md) — what to build, with P0/P1/P2 priorities. Build P0 first.
3. [document/planning.md](document/planning.md) — data schema, data flows, and the **Decision Log**. Decisions there are settled; do not re-open them unless requirements change.
4. [document/design_suggestions.md](document/design_suggestions.md) — rationale behind decisions and interview one-liners.
5. [document/prompt_devlog.md](document/prompt_devlog.md) — prompt version history and live-testing findings.

## Working practices (every session)

- **Document settled debates.** Whenever a design question is debated and agreement is reached, record it in [document/design_choise.md](document/design_choise.md) in plain, easy language: what was decided, why, and the alternative that was rejected. That file is the user's interview-prep notes. Never rewrite or restyle entries the user wrote themselves — append, or suggest corrections in chat.
- **Periodic grilling.** After each major completed slice, offer to run /grill-me so the user can practice defending the design and implementation under interview-style questioning before moving on.
- **The four pillars apply everywhere** (from design_suggestions.md): A. LLM latency (prefill vs decode, streaming, perceived latency); B. cost modeling and token budgeting; C. failure modes (provider rate limits/outages, garbage output, fallback strategy); D. idempotency of side effects (retries must never duplicate actions). Weigh them whenever designing, implementing, or discussing options — not only during grilling — and cover them in every /grill-me session. Adapt to this app's reality: the pillar list was written for a RAG app (no re-ranker here; caching applies to grading/chat, not vector chunks).

## Ground rules

- `demo/` is an exploratory prototype, kept for reference only. The real app is a fresh build (its multi-LLM fallback client is a pattern worth porting). Shared Neon database is fine — demo tables are prefixed `demo_`.
- Stack: Python, FastAPI, Pydantic, Postgres (Neon), Gradio UI mounted on FastAPI.
- All LLM calls use schema-constrained structured outputs validated by Pydantic.
- Prompts are versioned, tested artifacts — log why each prompt changed; failures feed the golden dataset.
- No password auth anywhere (see Decision Log #5). No Kafka, no Redis queue (see Decision Log #4).
