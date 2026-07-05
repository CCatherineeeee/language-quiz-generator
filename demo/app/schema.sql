-- Simplified, single-user version of the TDD data model.
-- Tables are prefixed `demo_` so they can share the Neon database safely.

CREATE TABLE IF NOT EXISTS demo_concepts (
    id          SERIAL PRIMARY KEY,
    code        TEXT UNIQUE NOT NULL,
    name        TEXT NOT NULL,
    kind        TEXT NOT NULL,            -- 'grammar' | 'vocab' | 'phrase' | 'comprehension'
    level       TEXT NOT NULL DEFAULT 'A1',
    description TEXT,
    status      TEXT NOT NULL DEFAULT 'proposed',  -- 'known' (user confirmed) | 'reference' (seed) | 'proposed'
    meta        JSONB,                    -- conjugation tables, disambiguation notes, etc.
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);
-- Migrations for databases created before these columns existed:
ALTER TABLE demo_concepts ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'proposed';
ALTER TABLE demo_concepts ADD COLUMN IF NOT EXISTS meta JSONB;

-- Single-row learner profile (single-user demo).
CREATE TABLE IF NOT EXISTS demo_profile (
    id            INT PRIMARY KEY DEFAULT 1 CHECK (id = 1),
    current_level TEXT,                   -- CEFR, e.g. 'A1'; inferred or user-set
    level_source  TEXT,                   -- 'suggested' | 'user'
    target_exam   TEXT NOT NULL DEFAULT 'tcf_canada',
    target_level  TEXT NOT NULL DEFAULT 'B2',
    updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);
INSERT INTO demo_profile (id) VALUES (1) ON CONFLICT (id) DO NOTHING;

CREATE TABLE IF NOT EXISTS demo_questions (
    id          SERIAL PRIMARY KEY,
    skill       TEXT NOT NULL,            -- reading | listening | writing | speaking
    level       TEXT NOT NULL DEFAULT 'B2',
    content     JSONB NOT NULL,           -- shape varies by skill
    status      TEXT NOT NULL DEFAULT 'active',
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demo_question_concepts (
    question_id INT NOT NULL REFERENCES demo_questions(id) ON DELETE CASCADE,
    concept_id  INT NOT NULL REFERENCES demo_concepts(id) ON DELETE CASCADE,
    PRIMARY KEY (question_id, concept_id)
);

CREATE TABLE IF NOT EXISTS demo_attempts (
    id           SERIAL PRIMARY KEY,
    question_id  INT NOT NULL REFERENCES demo_questions(id) ON DELETE CASCADE,
    answer       JSONB NOT NULL,
    submitted_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE TABLE IF NOT EXISTS demo_gradings (
    id             SERIAL PRIMARY KEY,
    attempt_id     INT NOT NULL REFERENCES demo_attempts(id) ON DELETE CASCADE,
    method         TEXT NOT NULL,         -- 'deterministic' | 'llm_judge'
    correct        BOOLEAN,
    scores         JSONB,                 -- rubric criterion -> band, for writing
    feedback       TEXT,
    created_at     TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- SM-2-lite review scheduling, keyed by concept.
CREATE TABLE IF NOT EXISTS demo_review_items (
    concept_id  INT PRIMARY KEY REFERENCES demo_concepts(id) ON DELETE CASCADE,
    easiness    REAL NOT NULL DEFAULT 2.5,
    interval    INT  NOT NULL DEFAULT 0,
    reps        INT  NOT NULL DEFAULT 0,
    due_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Every LLM call is logged (TDD: llm_calls is mandatory from day one).
CREATE TABLE IF NOT EXISTS demo_llm_calls (
    id         SERIAL PRIMARY KEY,
    provider   TEXT NOT NULL,
    model      TEXT NOT NULL,
    purpose    TEXT NOT NULL,             -- 'generation' | 'grading'
    ok         BOOLEAN NOT NULL,
    error      TEXT,
    latency_ms INT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- Conversational tutor history (the Chat tab).
CREATE TABLE IF NOT EXISTS demo_chat_messages (
    id         SERIAL PRIMARY KEY,
    role       TEXT NOT NULL,            -- 'user' | 'assistant'
    content    TEXT NOT NULL,
    meta       JSONB,                    -- e.g. {"actions": [...]} applied that turn
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- In-app notifications feed. Provider-switch notices land here.
CREATE TABLE IF NOT EXISTS demo_notifications (
    id         SERIAL PRIMARY KEY,
    kind       TEXT NOT NULL DEFAULT 'info',   -- 'provider_switch' | 'info' | 'error'
    message    TEXT NOT NULL,
    read       BOOLEAN NOT NULL DEFAULT false,
    created_at TIMESTAMPTZ NOT NULL DEFAULT now()
);
