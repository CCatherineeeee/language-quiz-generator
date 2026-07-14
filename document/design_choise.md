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
