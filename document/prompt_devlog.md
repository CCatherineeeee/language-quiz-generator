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

## AMBIGUITY_SYSTEM_V1 (2026-07-12)

Purpose: Analysis Layer stage 2 — detect when a reported language item has
several distinct meanings and nothing in the message resolves which one the
user learned (features.md's soirée example). Verdict-only by design: the prompt
explicitly forbids guessing the likely meaning; resolution comes from the
user's answer to clarification_question.

Iteration findings (live probe, 5 cases via Groq/llama-3.3-70b): 5/5 pass on
the first version — both ambiguous cases (soirée, temps) triggered with two
clean candidates + a usable clarification question; meaning-stated,
single-meaning, and grammar-point cases all stayed quiet.

Code-side guard (mirrors stage 1's no-op filter): an is_ambiguous=true verdict
with fewer than 2 candidates can't be acted on, so check_ambiguity() coerces it
to unambiguous. Not yet observed live; added defensively.

Probe cases seeded into evals/golden/ambiguity.jsonl.
