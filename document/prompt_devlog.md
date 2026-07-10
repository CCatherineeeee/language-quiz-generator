# Prompt Dev Log

One entry per prompt version: what it's for, what failed, what changed.
(Decision log #10: prompts are versioned, tested artifacts. Failures found here
become golden-dataset entries.)

## INPUT_CHECK_SYSTEM_V1 (2026-07-06)

First version of the spelling & grammar checker (Analysis Layer stage 1).
Design choices:

- Explicitly scoped to the target-language parts of a mixed English/French
  message, so English meta talk ("I learned the word ...") is never "corrected".
- "Do NOT invent issues" clause included from the start — over-correction is the
  known failure mode for this kind of prompt, and it's what the false-positive
  eval will measure later.
- Returns the exact original snippet per issue so the UI can highlight it.
- temperature 0.0 + Pydantic schema via complete_structured.

Iteration findings (live testing, 4-case probe via Groq/llama-3.3-70b):

- PASS: conjugation error ("j'ai apprendre" -> "j'ai appris", good explanation)
- PASS: clean French left untouched; pure English left untouched
- **FAIL: accent typo not flagged.** "I learned the word soireé today" returned
  has_issues=false, even though the prompt names this exact example. Hypothesis:
  a word quoted as vocabulary inside an English sentence isn't inspected
  closely; accents need an explicit inspection instruction.

-> superseded by V2.

## INPUT_CHECK_SYSTEM_V2 (2026-07-07)

Changes vs V1:

- Accent checking promoted to its own bullet with a stronger instruction:
  spell each word character by character; vocabulary quoted inside an English
  sentence must still be checked.
- Added a worked example (the V1 failure case, as input -> expected output).

Results: all 4 probe cases pass, including the V1 accent failure.

New quirk observed: on clean input the model kept has_issues=false but emitted a
no-op "issue" ("appris" -> "appris" with a "this is correct" explanation).
Handled in code, not in the prompt: check_input() drops issues where
original == corrected. Rationale: defensive post-processing is deterministic;
prompt wording against this could regress other cases.

All 4 probe cases (+ expected outputs) are seeded into the golden dataset:
evals/golden/input_check.jsonl.
