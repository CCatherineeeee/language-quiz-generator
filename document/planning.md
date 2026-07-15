# Data schema

- Definition: `language item" refers to a part of the language fact that word specific testing. For example, "je parle", "arbres", "des arbres".

## Table 1: User's SM-2 data `user_mastery_matrix`

This table tracks a user's learning progress and SM-2 data. Each user learnt language fact should have one row in this table:

| Field Name           | Data Type      | Constraints | Description                                                                                                                                                                                                                                                                                |
| :------------------- | :------------- | :---------- | :----------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **user_id**          | Integer / UUID | Foreign Key | Identifies the specific user.                                                                                                                                                                                                                                                              |
| **entity_id**        | Integer / UUID | Foreign Key | Points to `global_dictionary.id`. Tracks exactly which language item the user is practicing.                                                                                                                                                                                               |
| **next_review_date** | Timestamp      | Indexed     | The exact date/time the SM-2 algorithm dictates this token should be tested. Indexed so the database can fetch due cards instantly.                                                                                                                                                        |
| **interval**         | Integer        | Not Null    | SM-2 variable: The number of days to wait before the next review.                                                                                                                                                                                                                          |
| **ease_factor**      | Float          | Not Null    | SM-2 variable: The multiplier that shrinks or expands the interval based on user performance history.                                                                                                                                                                                      |
| **repetition**       | Integer        | Not Null    | SM-2 variable: count of consecutive successful reviews (quality >= 3). Resets to 0 on a failed review. The algorithm needs this alongside interval and ease_factor to pick the next interval.                                                                                              |
| **note**             | String         | Null        | Any user specific note about this language item to generate talored quiz, such as "user often get the spelling wrong", "user miss up with {another_word}'s meaning, etc. This field should be able to be updated after a quiz is done, or when user explicitly mention during first input. |

Primary key: composite `(user_id, entity_id)` — one row per user per language item.

## Table 2: Global dictionary `global_dictionary`

Stores every word, phrase, or grammar rule, shared across all users.

| Field Name       | Data Type      | Constraints                   | Description & Example                                                                                                                                                                                                  |
| :--------------- | :------------- | :---------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| **id**           | Integer / UUID | Primary Key                   | Unique identifier for each linguistic fact.                                                                                                                                                                            |
| **token**        | VarChar / Text | Not Null                      | The literal text string used for learning and prompting.<br><br>Example: "parler" or "je parle" or "la soirée".                                                                                                        |
| **type**         | VarChar        | Not Null                      | Categorizes the entity type so the LLM prompt generator knows how to frame the quiz question.<br><br>Example: root_noun, gender_collocation, conjugation.                                                              |
| **parent_id**    | Integer / UUID | Foreign Key(Self-Referential) | Points to the id of the parent root word. Why it's needed: It creates the web connection, letting the system know that "je parle" belongs to the root verb "parler". Allows for automatic feature unlocking.           |
| **meaning_note** | VarChar        | Nullable                      | Used only on root rows to differentiate words that look identical but have completely distinct meanings.<br><br>Example: Row A: "soirée" with note "evening party". Row B: "soirée" with note "duration of the night". |
| **language**     | VarChar        | Not Null                      | ISO code, e.g. "fr". v1 is French-only, but this column keeps adding a new language a data change instead of a schema migration.                                                                                       |
| **linguistic_metadata** | JSON    | Nullable                      | The LLM-extracted metadata object from the input pipeline, e.g. `{"part_of_speech": "noun", "gender": "feminine", "plural": "soirées"}`. Deliberately schema-free: different languages have different features (gender, measure words, cases), so no hardcoded columns per feature.      |

## Table_3: pending_quizzes

| Field Name    | Data Type      | Constraints | Description & Example                                               |
| :------------ | :------------- | :---------- | :------------------------------------------------------------------ |
| **id**        | Integer / UUID | Primary Key | Unique identifier for each pending quiz instance.                   |
| **user_id**   | Integer / UUID | Foreign Key | Connects the quiz directly to the practicing user.                  |
| **quiz_data** | JSON           | Not Null    | Holds the raw LLM-generated multiple choice questions or stories.   |
| **status**    | Enum           | Not Null    | Tracks state: `PENDING` (ready for user) or `COMPLETED` (finished). |
| **entity_ids** | JSON (Array)  | Not Null    | The `global_dictionary` IDs this quiz tests. Required so the SM-2 update step knows exactly which `user_mastery_matrix` rows to update after grading — without it, quiz results cannot be mapped back to learning state. |
| **created_at** | Timestamp     | Not Null    | When the quiz was generated. Useful for expiring stale pending quizzes whose items may no longer be due. |

## Table 4: `quiz_generation_jobs` (the Postgres job queue)

The queue for the async quiz worker (see design_suggestions.md "Queue Choice" for why this is a Postgres table and when we'd switch).

| Field Name     | Data Type      | Constraints | Description & Example                                                                            |
| :------------- | :------------- | :---------- | :----------------------------------------------------------------------------------------------- |
| **id**         | Integer / UUID | Primary Key | Unique job id.                                                                                    |
| **user_id**    | Integer / UUID | Foreign Key | Whose quiz to generate.                                                                           |
| **event_type** | Enum           | Not Null    | `NEW_ITEM_ADDED` or `USER_ITEMS_DUE`.                                                             |
| **payload**    | JSON           | Not Null    | The entity IDs to generate for.                                                                   |
| **status**     | Enum           | Not Null    | `PENDING` → `PROCESSING` → `DONE` / `FAILED`.                                                     |
| **attempts**   | Integer        | Not Null    | Retry counter; jobs exceeding the max go to `FAILED` (dead-letter) for manual inspection.         |
| **created_at** | Timestamp      | Not Null    | Enqueue time; with pickup/finish logs this gives the full event lifecycle.                        |

Workers claim jobs with `SELECT ... FOR UPDATE SKIP LOCKED` so concurrent workers never grab the same job. Enqueue happens in the same transaction as the user-facing write (e.g. adding a word), so a job can never be lost between the two.

## Table 5: `users`

Only two rows in v1: the owner account and the demo account (see design_suggestions.md "Account Model").

| Field Name       | Data Type      | Constraints | Description                                                    |
| :--------------- | :------------- | :---------- | :-------------------------------------------------------------- |
| **id**           | Integer / UUID | Primary Key | User id referenced by all other tables.                         |
| **display_name** | VarChar        | Not Null    | e.g. "Catherine", "Demo".                                       |
| **is_demo**      | Boolean        | Not Null    | Demo account gets nightly state reset; owner account never does. |

## Data Flows

How data should be crud in each scenarios

### Full input-to-quiz flow (one diagram)

```
user types "I learned the word soirée"
        |
        v
[0] API guardrail (no LLM): length check            [BUILT]
        |--> too long? --> 413 error, stop
        v
[1] Spelling & grammar check (LLM, schema-validated) [BUILT, prompt V3]
        |--> mistake found? --> show correction, user confirms corrected text
        v
[2] Ambiguity check (LLM, schema-validated)          [BUILT, prompt V1]
        |--> ambiguous? --> STOP, ask user: "evening, party, or both?"
        |                   --> user's answer resolves it (LLM never guesses)
        v
[3] Meta-extractor (LLM)                             [BUILT, prompt V1]
        --> storage-ready items (token/type/sense/metadata/parent)
        --> related-form suggestions ("also know the plural?")
        v
[4] Confirm-first: "Save soirée = 'evening party'?" --> user says yes
        v
[5] STORAGE TRANSACTION (one Postgres transaction,   [SPEC ONLY]
    all-or-nothing — see spec in progress.md):
        --> insert global_dictionary row(s)   (2 rows if both meanings)
        --> insert user_mastery_matrix row(s) (SM-2 initial values)
        --> insert quiz_generation_job        (eager generation)
        v
[6] Chat replies: "Saved! A quiz is being prepared."
        |
        v  (background worker, async)                [SPEC ONLY]
[7] Worker claims job (SKIP LOCKED) --> generate_quiz_judged()
    (generate -> judge -> <=1 retry)                 [SERVICES BUILT]
        --> saves to pending_quizzes keyed by job_id
        v
[8] User takes quiz --> grading (MCQ: no LLM;        [SERVICES BUILT]
    typed: fast path or LLM) --> SM-2 update         [SPEC ONLY]
```

### A New Word is Learned

When user say that they have learned a new word, the application should:
step 1: populates `user_mastery_matrix` with this word.
step 2: grab all other related language item (such as conjugation, plural form, gender form, etc) to ask if user also want to mark them as learnt.
step 3: If user said yes, then repeate step 1 for each language item

### Quiz Generation

1. This should be async task, so that when user is read to start quiz, they won't experience a long waiting time.
   step 1: background worker searches for items that are due today `SELECT entity_id FROM user_mastery_matrix WHERE user_id = 5 && next_review_date <= NOW()`
   step 2: The database returns a list of due IDs
   step 3: The database returns a list of due IDs. Let's look at one specific due item:

entity_id: 205 (which maps to token: "la soirée", type: gender_collocation) 2. The Execution Logic
The background worker takes the literal string "la soirée" and the type "gender_collocation".

It sends a highly constrained payload to the LLM:

JSON
{
"target_token": "la soirée",
"rule_type": "gender_collocation",
"instructions": "Generate a French sentence-completion multiple choice question. The correct answer must force the user to recognize that 'soirée' is feminine by selecting 'la' over 'le'."
}
The LLM processes this instantly because it doesn't have to figure out what grammatical rule to test—the token "la soirée" is the rule.

The LLM returns a structured JSON quiz question, which the background worker validates via Pydantic and saves to the user's upcoming quiz cache.

### Two event triggers for quiz generator

Your event queue (Redis Streams, or a Postgres-backed job table — Kafka is deliberately avoided: it is overkill for this load, and "why Kafka for a single-developer app?" is an interview question you don't want) listens for two distinct event messages that route straight into the quiz-generation-pipeline:

USER_ITEMS_DUE: A daily cron scheduler checks the user_mastery_matrix and publishes a list of expired entity IDs to the queue.

NEW_ITEM_ADDED: The moment a user submits a newly encountered language point, an event is immediately published to the queue with the newly generated IDs.

Inside the Background Consumer
[Raw Event Received] ➔ [Fetch Token Details & Error Notes via Join] ➔ [Collapse by Parent_ID] ➔ [Fire LLM Request (Schema-constrained + low temp)] ➔ [Validate Response] ➔ [Write to pending_quizzes Table]
This ensures that regardless of whether an item is old and due, or brand new, it passes through the exact same collapsing, optimization, and generation code pipeline seamlessly.

# Logging

Step 1: Use Structured JSON Logging
In Spring Boot or Python, configure your standard logger (like Logback/Slf4j) to output logs as structured JSON strings instead of plain text sentences.
Bad Log (Hard to search): INFO: Worker processed quiz for user 5 and it succeeded.
Good Log (Machine-readable):{"timestamp": "2026-07-04T18:21:00Z", "level": "INFO", "event": "QUIZ_GENERATION_SUCCESS", "user_id": 5, "duration_ms": 1420}

Step 2: Leverage LLM-Specific Tracing (Optional but high-signal)
If you want to look incredibly professional, plug in an open-source LLM tracing library like Langfuse or LangSmith. These are lightweight SDKs you drop into your backend code with two lines of configuration. They automatically record every prompt, response, token count, cost, and latency spike into a beautiful, ready-made dashboard.

# Decision Log (settled pre-implementation, July 2026)

Binding decisions with reasoning. A new session should read this before writing code, and not re-open these unless requirements change. Longer rationale and interview one-liners live in design_suggestions.md; priorities (P0/P1/P2) live in features.md.

## 1. Fresh build; demo/ is a prototype, not the base

The portfolio app is written from scratch in a new package. `demo/` was an exploratory play-try; it stays in the repo for reference (its multi-LLM fallback client in `demo/app/llm/` is a pattern worth porting). The app may share the same Neon database — demo tables are prefixed `demo_`, so there is no collision.

## 2. Stack: Python, FastAPI, Pydantic, Postgres (Neon)

All LLM calls go through schema-constrained structured outputs validated by Pydantic — that is the correctness guarantee. Low temperature only reduces variance; it does not make inference deterministic and is never relied on for correctness.

## 3. Scope: French-only v1, multi-language by design

Only French ships in v1 (keeps prompt iteration tractable). Extensibility is preserved in data, not code: `global_dictionary.language` plus the schema-free `linguistic_metadata` JSON mean a new language is new rows and new prompt examples, never a schema migration or new columns.

## 4. Queue: Postgres job table (`quiz_generation_jobs`)

Chosen over Redis Streams and Kafka. Why: (a) enqueue happens in the same transaction as the user-facing write, so jobs cannot be lost between two systems; (b) Postgres already gives durability, and a lost quiz job is a real bug while our load is a few events per minute; (c) `FOR UPDATE SKIP LOCKED` makes concurrent workers safe. Switch triggers: Redis Streams at hundreds of jobs/second; Kafka only for multi-consumer replayable fan-out. Extension path: keep produce/consume behind a small interface so the backing store can change without touching producers or the worker.

## 5. Accounts: exactly two, no password auth

Demo account is the default (pre-seeded; nightly job resets it to the seed snapshot). Owner account for real learning sits behind a single shared secret from an env var (sets a cookie). No password column exists anywhere — hand-rolled auth earns nothing and sloppy auth in a public repo actively hurts. Extension path: every table is keyed by `user_id`, so real auth (bcrypt/argon2) is an additive P2 feature, not a migration.

## 6. UI: Gradio chat mounted on FastAPI

`gr.mount_gradio_app` on the FastAPI app; chat is the primary surface (report learning, answer clarifications, take quizzes). All logic lives behind FastAPI routes — Gradio is a thin client, so the P2 custom frontend (quiz cards) replaces it without backend changes.

## 7. Delivery: buildpack deploy, no Docker Compose, CI deferred

Deploy via platform buildpacks (platform TBD; hard requirement: always-on, no cold start for recruiters). No Docker Compose. GitHub Actions is P2; until it exists, the eval gate is manual discipline: run the golden-dataset eval locally before every deploy and commit the regenerated README score table. LLM key gets a hard monthly spend cap because the demo is public.

## 8. Evals: golden dataset is the public proof

The golden dataset is seeded from real failures found during prompt iteration. The README carries an auto-generated score table (per-category scores, grading false-negative rate, stamped with date + model + prompt version). Deploy threshold: 4.5/5.

## 9. SM-2 behind a scheduler interface

SM-2 (interval, ease_factor, repetition) is v1. Implement it as a pure function behind a small scheduler interface so FSRS (the modern successor) can replace it later without touching callers — and mention that in interviews.

## 10. Working practice: prompts are versioned, tested artifacts

Keep every prompt under version control with a short dev log of why it changed. Iteration failures become golden-dataset entries. This log doubles as interview material.

## 11. Dependencies: uv + pyproject.toml (instead of pip + requirements.txt)

In easy words: with pip, the list of packages (requirements.txt) easily fills with clutter, because `pip freeze` writes down everything installed — including dependencies of dependencies — and nothing marks which packages we actually chose. With uv, `pyproject.toml` holds only what we explicitly added, and `uv.lock` records the exact version of everything else, so any machine (laptop, CI, server) rebuilds the identical environment with `uv sync`. Bonus: removing a package also removes the sub-packages it dragged in; pip leaves those orphans behind. Note: neither tool can tell whether the code actually uses a package — that stays our job.

Interview line: "pyproject.toml records intent, uv.lock records the exact resolved versions — so dev, CI, and prod install identical dependencies. requirements.txt conflates the two."

## 12. Schema changes: Alembic migrations (instead of create_all / hand-written ALTERs)

In easy words: SQLAlchemy's `create_all()` only creates tables that don't exist — it never alters an existing one. So once a table holds real data (and the owner account holds my real learning data), adding a column would mean hand-written `ALTER TABLE` with no record of what ran where. Alembic is git for the schema: every change is a small versioned script with upgrade/downgrade, mostly auto-written by diffing our models against the live database (`alembic revision --autogenerate`, then `alembic upgrade head`). Autogenerate can't detect renames (it sees drop + add), so every generated script gets a human review before running.

Interview line: "Versioned migrations, autogenerated then hand-reviewed; rollback is the downgrade script. For zero-downtime you make changes backwards-compatible: add the new column, ship code that writes both, then drop the old one (expand/contract)."
