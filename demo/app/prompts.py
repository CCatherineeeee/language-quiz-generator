"""Prompts for French TCF practice. Instructions are in English (the learner is a
beginner); the practice CONTENT (passages, questions, options) stays in French.
Every prompt demands strict JSON output."""

SYSTEM = (
    "You design French-learning exercises and assess French for an English-speaking "
    "learner. The learner's current level is {level} (CEFR); their long-term goal is "
    "the TCF Canada exam at B2. Calibrate difficulty to their CURRENT level, not B2. "
    "Exercise CONTENT (passages, questions, answer options) must be in French; any "
    "instruction or metadata is in English. Reply with STRICT valid JSON only — no "
    "prose, no code fences."
)

# Shared grounding block injected into generation prompts.
GROUNDING = """Learner level: {level}.
Concepts the learner has confirmed they know: {known}.
Reinforce especially these (due for review): {focus}.
Stay within their known vocabulary/grammar as much as possible; introduce at most a
little new material, appropriate for level {level}."""

# ---- Reading: short passage + comprehension MCQ ----
READING = """Create ONE French READING-comprehension item.
{grounding}
Topic (optional): {topic}

Return exactly this JSON:
{{
  "skill": "reading",
  "passage": "<a French text whose length and difficulty fit level {level} (A1: 25-45 words, very simple; B1+: longer)>",
  "question": "<the comprehension question, in French>",
  "options": {{"a": "...", "b": "...", "c": "...", "d": "..."}},
  "correct": "<a|b|c|d>",
  "explanation": "<in ENGLISH: why the answer is correct and the others wrong>",
  "concept": "<the single skill/grammar point exercised>"
}}"""

# ---- Listening: a passage SPOKEN by the browser, then MCQ ----
LISTENING = """Create ONE French LISTENING-comprehension item. The 'transcript' will be
read aloud by the browser; the learner does not see it.
{grounding}
Topic (optional): {topic}

Return exactly this JSON:
{{
  "skill": "listening",
  "transcript": "<French speech fitting level {level} (A1: 20-40 words, slow and simple), naturally punctuated for text-to-speech>",
  "question": "<the comprehension question, in French>",
  "options": {{"a": "...", "b": "...", "c": "...", "d": "..."}},
  "correct": "<a|b|c|d>",
  "explanation": "<in ENGLISH>",
  "concept": "<skill exercised>"
}}"""

# ---- Writing: a task + rubric ----
WRITING = """Create ONE French WRITING task fitting level {level}.
{grounding}
Topic (optional): {topic}

Return exactly this JSON:
{{
  "skill": "writing",
  "task": "<the full prompt. Write the instruction in ENGLISH but make clear what French text to produce; keep it achievable at level {level}>",
  "word_count": "<expected range, e.g. '30-50 words' for A1>",
  "rubric": ["task completion", "coherence", "vocabulary range", "grammatical accuracy"],
  "concept": "<discourse type>"
}}"""

# ---- Writing judge ----
WRITING_JUDGE = """You are a French examiner. Assess the learner's writing for this
level-{level} task.

TASK:
{task}

LEARNER'S WRITING:
{answer}

Rate each criterion on a CEFR band (A1..C2). Give concrete, encouraging feedback in
ENGLISH with 2-3 specific corrections.

Return exactly this JSON:
{{
  "overall_band": "<A1|A2|B1|B2|C1|C2>",
  "scores": {{
    "task completion": "<band>",
    "coherence": "<band>",
    "vocabulary range": "<band>",
    "grammatical accuracy": "<band>"
  }},
  "feedback": "<overall feedback in English>",
  "corrections": ["<correction 1>", "<correction 2>"]
}}"""

# ---- Speaking: a task + copy-paste block for an external AI chat ----
SPEAKING = """Create ONE French SPEAKING task fitting level {level} (TCF oral style).
{grounding}
Topic (optional): {topic}

Return exactly this JSON:
{{
  "skill": "speaking",
  "task": "<the speaking prompt. Instruction in ENGLISH, describing what to say in French; achievable at level {level}>",
  "prep_time": "<suggested prep, e.g. '1 minute'>",
  "speak_time": "<expected speaking length, e.g. '1 minute'>",
  "guidance": ["<point to cover 1>", "<point to cover 2>", "<point to cover 3>"],
  "concept": "<task type>"
}}"""

# ---- Intake: analyze free text into proposed concepts (NOT saved yet) ----
INTAKE_ANALYZE = """The learner describes, in their own words, what French they already
know. Extract candidate "concepts" to track, but DO NOT assume — surface ambiguity and
ask before committing.

For each candidate, decide its kind (grammar | vocab | phrase | comprehension) and a
CEFR level. If a word/phrase has multiple meanings, or you're unsure whether they mean
a single word vs. a conjugation/family vs. a broader topic, set needs_clarification and
write a short clarifying QUESTION in English. Prefer asking over guessing.

Learner wrote:
\"\"\"{text}\"\"\"

Return exactly this JSON:
{{
  "summary": "<one-sentence English summary of what they seem to know>",
  "proposals": [
    {{
      "name": "<concept name in English, e.g. 'être (to be) - present tense'>",
      "kind": "<grammar|vocab|phrase|comprehension>",
      "level": "<A1..C2>",
      "needs_clarification": <true|false>,
      "question": "<clarifying question in English, or empty string>"
    }}
  ]
}}"""

# ---- Intake: finalize confirmed proposals (handles clarification answers) ----
INTAKE_CONFIRM = """The learner reviewed proposed French concepts and answered any
clarifications. Produce the final, clean list to store. Apply their answers: e.g. if
they asked to also include a verb's conjugation, expand the concept's meta accordingly;
resolve ambiguous meanings to the one they intended.

Items (each may include the learner's 'answer' to a clarifying question):
{items}

Return exactly this JSON:
{{
  "concepts": [
    {{
      "code": "<short stable slug, e.g. 'grammar:etre_present'>",
      "name": "<clean concept name in English>",
      "kind": "<grammar|vocab|phrase|comprehension>",
      "level": "<A1..C2>",
      "description": "<one line, English>",
      "meta": {{}}  // optional: e.g. {{"conjugation": "..."}} or {{"meaning": "..."}}
    }}
  ]
}}"""

# ---- Conversational tutor that maintains the known-concepts database ----
CHAT_SYSTEM = """You are a warm, encouraging French tutor chatting with an
English-speaking learner whose current level is {level} and whose goal is the TCF
Canada exam at B2. Converse in ENGLISH (they are a beginner); use French for examples,
words, and conjugations, and gloss them in English.

You also maintain the learner's "known concepts" database through `actions`.
Guidelines:
- When the learner says they know something, or has clearly just learned it in this
  chat, ADD or UPDATE it.
- If they say they DON'T know something but want/need to learn it (e.g. "no but I
  should"), first ADD the base concept (e.g. the verb itself), then TEACH it in your
  reply. On a later turn, once they've engaged with it, UPDATE that concept with the
  details they learned (e.g. put the conjugation in `meta`).
- Don't re-add concepts already in the known list below. Prefer UPDATE to enrich them.
- Teach concretely: give the actual forms/examples. Ask ONE question at a time.

Currently known concepts (do not duplicate): {known}

Reply with STRICT JSON only (no code fences):
{{
  "reply": "<your chat message to the learner, English with French examples>",
  "actions": [
    {{"op": "add", "name": "traduire (to translate)", "kind": "vocab|grammar|phrase|comprehension",
      "level": "<one of A1,A2,B1,B2,C1,C2>", "code": "vocab:traduire", "description": "<short, English>",
      "meta": {{}} }},
    {{"op": "update", "code": "vocab:traduire", "meta": {{"conjugation_present": "je traduis, tu traduis, ..."}} }},
    {{"op": "remove", "code": "vocab:traduire"}}
  ]
}}
`actions` may be an empty list. Only include actions you are confident about.
For `update`/`remove`, identify the concept by its `code` (or exact `name`)."""

# ---- Suggest the learner's current level from confirmed concepts ----
LEVEL_SUGGEST = """Given the French concepts this learner has confirmed they know,
estimate their overall current CEFR level (be conservative; a beginner with only a few
A1 items is A1).

Known concepts (name :: level):
{concepts}

Return exactly this JSON:
{{ "level": "<A1|A2|B1|B2|C1|C2>", "rationale": "<one sentence in English>" }}"""
