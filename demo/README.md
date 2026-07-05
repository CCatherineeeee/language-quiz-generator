# French Trainer (demo) · toward TCF B2

A personal, runnable French practice app. Your **goal** is the TCF Canada exam at B2,
but exercises are generated at **your current level** (default A1) and built from the
concepts **you've confirmed you know** — not generic B2 content. English UI, light
theme. A simplified, working slice of the `Language_app_TDD.pdf` design (FastAPI +
Postgres/Neon + a single-page UI).

## How personalization works (important)

Exercises are **not** generic and are **not** hallucinated from nothing. Each one is
grounded in your data:

1. **Tell it what you know** — in *My progress*, type in plain English what you've
   learned. The LLM proposes concepts, flags ambiguities (a word with several meanings,
   "do you also want the conjugation?") and **asks before saving anything**. You review,
   answer, and confirm. Nothing enters your "known" set without confirmation (the TDD's
   load-bearing rule).
2. **Your level is inferred** from those concepts (you can still override it).
3. **Generation reads your level + known concepts**, reinforces ones **due for review**
   (SM-2-lite spaced repetition), and introduces only a little new material.

If you haven't added anything yet, the app says so and falls back to basic A1.

## The four skills

| Skill | In the app |
|-------|-----------|
| **Reading** | LLM generates a level-appropriate French passage + comprehension MCQ. Deterministic grading + English explanation. |
| **Listening** | LLM generates a transcript; your **browser speaks it** (Web Speech API, no audio files stored), then MCQ. Transcript revealed after answering. |
| **Writing** | LLM generates a writing task at your level; you write in French; an **LLM judge** grades on a CEFR rubric with English feedback + corrections. |
| **Speaking** | LLM generates a speaking task + a **ready-to-copy prompt** you paste into any AI chat (e.g. Claude on your phone) to be graded and taught. No in-app audio. |

Instructions/feedback are in English (light support for beginners); the practice
content stays in French. Full `demo_llm_calls` logging is included, mirroring the TDD.

## Multi-LLM free-tier fallback

The whole point of the requested change. `app/llm/providers.py` holds an ordered
list of OpenAI-compatible free providers:

```
Groq  →  Gemini  →  (OpenRouter / Cerebras, when you add keys)
```

When a provider is **out of quota or rate-limited**, the client logs it, **switches
to the next provider**, and posts a **system message into the Chat tab** ("🔁 'groq'
is out of quota. Switched to 'gemini'."). The full request (including the whole
conversation, for chat) is re-sent to the fallback provider, so **history carries over**.

### Add another free provider later
1. Uncomment its entry in `app/llm/providers.py` (or add a new `Provider(...)`).
2. Put its key in the project-root `.env` or `demo/.env`.
That's it — the fallback chain picks it up automatically.

## Setup & run

Keys live in the **project-root `.env`** (already has `DATABASE_URL` for Neon and
`GROQ_API_KEY`). To enable Gemini fallback, add `GEMINI_API_KEY=...` there.

```bash
bash demo/run.sh
# → http://127.0.0.1:8000
```

`run.sh` installs deps, creates the `demo_*` tables, seeds a small B2 taxonomy, and
starts the server.

## Layout

```
demo/
  app/
    main.py            FastAPI routes
    config.py          env + exam/skill settings
    db.py              psycopg helper, schema init
    schema.sql         demo_* tables (incl. profile, concept status/meta)
    store.py           LLM-call logging, system chat notices, client factory
    prompts.py         generation, judge, intake, level-suggest prompts
    seed.py            A1->B2 reference taxonomy seed
    llm/
      providers.py     ordered free-provider registry (extensible)
      client.py        fallback client + chat notifications
    services/
      profile.py       learner level + LLM level suggestion
      intake.py        confirm-first "what I know" -> known concepts
      generation.py    per-skill generation, grounded in level + concepts
      grading.py       MCQ (deterministic) + writing (LLM judge)
      review.py        SM-2-lite scheduling
  static/              single-page UI (index.html, app.js, style.css)
```

Tables are prefixed `demo_` so they coexist safely in the shared Neon database.
