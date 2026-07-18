This document is for documenting things I learnt, along with arguments and concent I've made with coding agent during development for this project.

# Input analysis

Input analysis is mainly done with 3 parts: prompts (tell llm check spelling and gramma, look for ambiguity (soirée means night and party)), schema (validates llm response JSON, which isn't guaranteed to be in right format always), function (the service function the rest of the code calls).

# Postgres for queue

Postgres is chosed for holding queue for this app, as we don't expect to have too many event message for this app. It's unnessary and too expensive to configure another service (such as Redis, Kafka) for this app's queue.
However, with a larger amount of event message data, we should consider service like Redis or Kafka to be able to large amount of messages.

# Why not docker

No Dockerfile needed for deploy (buildpacks handle it).

# Account Auth

For this app, I'm mainly using it for two purpose right now: my personal language learning; job hunting project portfolio demo. Ask every recruitor or interviewer to create an account on this app is too much. Thus, it doesn't need a too complicated or secured authenticate system to store accounts and passwords.

# Why not Redis for the queue, if we use Redis anyway (for rate limiting)?

(agreed 2026-07: Redis will be added later for API rate limiting, so "one less service" is not the real reason to keep the queue in Postgres. The real reasons:)

1. The two jobs tolerate losing data very differently. If Redis loses a rate-limit counter, someone gets a few extra free requests — harmless. If Redis loses a queue event, a user's quiz silently never gets generated — a real bug. So a queue on Redis must be configured durable (persistence settings, paid tier that guarantees it), which is extra work and cost we'd now own. The rate limiter can run on cheap, even flaky Redis.
2. The dual-write problem. Saving the word goes to Postgres, but the event would go to Redis — two systems. If the app crashes between the two writes, the event is lost forever. The textbook fix is an "outbox": write the event into a Postgres table inside the same transaction, then copy it to Redis. But at our tiny load, that outbox table already IS a perfectly good queue — copying it into Redis afterward adds a moving part with zero gain.
3. Timing: the queue is P0 (core loop), the rate limiter is P1. Using Redis for the queue would drag Redis into the core build earlier.

Interview line: same-transaction enqueue means adding a word and queueing its quiz job either both happen or both roll back — an external queue can't give me that without an outbox, and the outbox would just be this table.

# Storage transaction: why meaning_note is part of the dictionary match key

(agreed 2026-07-17/18)

When saving a confirmed word, we look it up by (token, type, language, meaning_note) and only create a new row if no exact match exists. meaning_note is in the key so "soirée = evening" and "soirée = party" stay separate rows with separate review schedules. The lookup is one WHERE clause with equality on four columns — cheap, and indexable later if the table grows.

Known weakness (I found this one): meaning_note is LLM-generated free text, so the LLM might say "night" for a word stored as "evening" — exact match misses, and we get a near-duplicate row. v1 accepts this risk (confirm-first means a human sees the wording before saving; duplicates are repairable). The proper fix is the v2 extractor rewrite below.

# Storage transaction: parent links resolved inside the batch, fail loudly

(agreed 2026-07-18)

Problem: the extractor names a child's parent as text ("mangé" → parent "manger"), but the dictionary links rows by integer id, and the parent may be new in the same confirmed batch (no id yet).

Decision: inside the one transaction, insert parentless items first and remember their new ids in an in-memory dict. A child's parent_token is looked up in that dict first, then in global_dictionary. If it matches nothing, the whole batch is rejected and rolled back, because saving a child with a broken parent link would silently corrupt the word graph — better to fail loudly and surface the extractor bug.

Rejected alternative: pre-building the whole dictionary with a cron job so parents always exist. Too many tokens spent on words nobody may learn, and context-free bulk generation can't know user-specific meanings.

# Extractor v2 plan: cache-aside (my design, to be built and measured)

(agreed 2026-07-18)

v1 ships as-is: the extractor calls the LLM for metadata on every message, and the storage transaction populates global_dictionary. v2 (features.md P2 "dictionary-aware extraction", my design): before the LLM call, look each reported token up in global_dictionary — on a hit, reuse the stored metadata and meaning_notes (prompting "if the user means one of these, reuse its exact meaning_note"), on a miss, generate once and store. This is the cache-aside pattern: check the store first, only call the expensive thing on a miss, write the result back.

Plan: land v2 after the core loop works, then compare LLM calls and output tokens per stored word before vs after. Interview story: shipped the simple version first, then measured my optimization instead of assuming it helps.
