# Language Quiz Generator

Resume portfolio project (targets: AI engineer and backend engineer roles). An LLM-powered language-learning app: users report what they learned in chat, the app extracts structured linguistic knowledge, schedules it with SM-2 spaced repetition, and generates personalized quizzes via an async worker.

## Read before implementing

1. [document/features.md](document/features.md) — what to build, with P0/P1/P2 priorities. Build P0 first.
2. [document/planning.md](document/planning.md) — data schema, data flows, and the **Decision Log**. Decisions there are settled; do not re-open them unless requirements change.
3. [document/design_suggestions.md](document/design_suggestions.md) — rationale behind decisions and interview one-liners.

## Ground rules

- `demo/` is an exploratory prototype, kept for reference only. The real app is a fresh build (its multi-LLM fallback client is a pattern worth porting). Shared Neon database is fine — demo tables are prefixed `demo_`.
- Stack: Python, FastAPI, Pydantic, Postgres (Neon), Gradio UI mounted on FastAPI.
- All LLM calls use schema-constrained structured outputs validated by Pydantic.
- Prompts are versioned, tested artifacts — log why each prompt changed; failures feed the golden dataset.
- No password auth anywhere (see Decision Log #5). No Kafka, no Redis queue (see Decision Log #4).
