When building and preparing to defend your system, focus deeply on these four pillars:A. The Physics of LLM Traffic & LatencyInterviewers will grill you on how you handle slow response times. You need to distinguish between Prefill Phase Latency (processing the prompt) and Decode Phase Latency (generating tokens one by one).Your Design Defense: Explain how you used streaming responses to improve perceived latency (keeping TTFT under 400ms). Mention implementing a cross-encoder re-ranker to filter 50 rough vector chunks down to the 5 most critical ones, keeping your prompt lean and saving costs.B. Cost Modeling & Token BudgetingIf you tell an interviewer you just pipe massive amounts of text into an expensive model on every API request, you will lose points.Your Design Defense: Implement and talk about semantic caching. If a user asks a question that has a 95% embedding similarity to a question asked five minutes ago, your system should bypass the LLM entirely and serve the cached answer from Redis, treating tokens as a literal financial budget. C. Defensive Engineering & Failure ModesWhat happens when your LLM provider hits a rate limit, experiences an outage, or the model outputs complete garbage that breaks your code?Your Design Defense: Design an LLM Gateway layer that implements exponential backoff, a circuit breaker pattern, and an automatic fallback model strategy (e.g., if a complex model rate-limits or times out, the system automatically falls back to a faster, lighter model to maintain application uptime).D. Agent IdempotencyIf your agent has a tool that triggers a real-world action (like modifying a record in a database or sending an email) and the LLM call times out mid-request, what happens if the agent tries it again?Your Design Defense: Ensure that any side-effect tool used by your orchestrator implements strict idempotency keys so that duplicate retries by a confused agent never result in duplicate actions in your system.

# Queue Choice: Postgres Job Table (over Redis Streams and Kafka)

## The decision

The async quiz pipeline uses a plain Postgres table as its job queue. Producers (word added, daily due-items sweep) insert job rows; the background worker polls with `SELECT ... FOR UPDATE SKIP LOCKED`, which lets multiple workers safely grab different jobs without stepping on each other.

## Why Postgres wins here

1. **Atomic enqueue.** Adding a word and enqueuing its quiz job happen in one database transaction: both succeed or both roll back. With an external queue (Redis/Kafka) there are two systems, so a crash between "DB saved" and "event published" silently loses the job. The standard fix is an outbox table in Postgres — and at our load, that outbox table simply IS the queue. Adding Redis after it would just move the same rows again.
2. **Right durability for the job.** A lost queue event means a user's quiz silently never generates. Postgres is already our durable source of truth. Making Redis equally durable means owning AOF persistence settings and paying for a managed tier that guarantees them.
3. **Honest scale.** This app sees a few events per minute. Polling every few seconds is invisible to users, especially since quizzes are generated eagerly right after input.

Note: Redis still enters the stack later for API rate limiting — a job it fits well, because a lost rate-limit counter is harmless while a lost queue event is a bug.

## When we would switch

- **To Redis Streams (or another broker):** when sustained throughput reaches hundreds of jobs per second. At that point the job table becomes a hotspot — lock contention, plus vacuum pressure because every finished job is an UPDATE/DELETE leaving dead tuples — and we would also want push delivery instead of polling.
- **To Kafka:** for fan-out, not speed. When several independent consumers need the same event stream (quiz generation + analytics + audit log), with replay (reprocess last week's events after a bug fix) and long retention. Kafka is an org-scale event log; one app with one worker cannot pay back its operational cost.

## Interview one-liner

"I used Postgres as my queue because my load didn't justify a second system: I get transactional enqueue for free and SKIP LOCKED makes concurrent workers safe. I'd move to Redis Streams at hundreds of jobs per second, and to Kafka when multiple consumer groups need replayable fan-out."

# Account Model: Two Accounts, No Password Auth

## The decision

v1 has exactly two accounts. The demo account is the default — anyone opening the URL lands in it, pre-seeded with vocabulary and due quizzes. The owner (real learning) account sits behind a single shared secret checked against an environment variable, which sets a cookie. A nightly job resets the demo account to its seeded snapshot, so every visitor gets a clean first impression even though visitors share the account between resets.

## Why no password auth

Hand-rolled login is commodity code that earns no interview points, and it carries the one risk that actively hurts: sloppy password handling in a public repo is a negative signal. Doing nothing beats doing it simply. The schema still carries `user_id` on every table, so real multi-tenancy is a schema-compatible P2 (with proper bcrypt/argon2), stated in the roadmap.

## Interview one-liner

"Auth was deliberately deferred: the demo needs exactly two trust levels, so I used an env-var secret for the owner and a nightly-reset public demo account. Every table is keyed by user_id, so real auth is an additive change, not a migration."

# UI: Gradio Chat Mounted on FastAPI

## The decision

v1 UI is Gradio, mounted inside the FastAPI app (`gr.mount_gradio_app`), centered on a chat interface: the user reports what they learned, clarification questions appear in the chat, and quizzes render as chat messages. FastAPI stays the real product — all logic lives behind its API routes; Gradio is a thin client over them.

## Why

The portfolio targets are AI engineer and backend engineer, so frontend polish buys little. Gradio gives a working chat UI in hours instead of weeks, is a recognized tool in AI engineering, and keeps the whole project in Python. A custom frontend (the quiz-card walkthrough prototype) stays on the P2 roadmap.

# Cost optimization

think about cost optimization
Model-tier routing — extraction and classification steps don't need your primary model; route them to a cheaper tier. Often the single biggest cut.
Prompt caching — your system prompt and tool definitions repeat every call; caching cuts input cost substantially on repeated prefixes.
Output length control — cap max_tokens per tool; structured JSON outputs waste fewer tokens than prose.
Judge sampling — running your 3-layer judge on every generation is expensive; sample a percentage once quality stabilizes, and keep 100% only for regression sets.
