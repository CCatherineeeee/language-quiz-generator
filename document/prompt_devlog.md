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

## INPUT_CHECK_SYSTEM_V3 (2026-07-14) — first production-found bug

A real user test on the Render deployment: bare input "dentifice" (misspelled
dentifrice) returned has_issues=false. Reproduced locally — V2 missed it even
inside a sentence. Root cause: V2 checks accents and grammar but never asks
"does this word exist in {language}?".

V3 changes: three explicit passes (word existence -> accents -> grammar),
bare-word inputs named as a first-class input shape, dentifice worked example.

Iteration findings:

- dentifice fixed (bare + in sentence) on first V3 draft.
- **New failure: V3 translated English.** "toothpaste" -> "dentifrice",
  has_issues=true. Fix: "correcting means fixing spelling, NEVER translating;
  return real English words unchanged."
- **Inconsistent output on bare "soireé":** corrected_input was right but
  has_issues=false with empty issues. Fixed in code, not prompt: if
  corrected_input != input, has_issues is forced true and a generic issue is
  synthesized. Deterministic consistency beats prompt pleading.
- **Run-to-run variance measured:** the accent-in-english-frame golden passed,
  failed, then passed again across identical temp-0 runs. Added a "work word
  by word, never skip a word inside an English sentence" instruction; 3
  consecutive full-suite passes after. Lesson for the eval suite: run goldens
  N times and report pass rates, not single-run pass/fail.
- **Known open issue (LLM client, not prompt):** Groq JSON mode intermittently
  dies with "max completion tokens reached before generating a valid document"
  (HTTP 400, json_validate_failed) — the model loops before emitting valid
  JSON. With no fallback key configured this surfaces as AllProvidersFailed.
  Needs a client-level same-provider retry for transient generation failures.

## EXTRACTION_SYSTEM_V1 (2026-07-14)

Meta-extractor (pipeline stage 3): checked+disambiguated report -> storage-ready
items (token/type/meaning_note/linguistic_metadata/parent_token) + max 5
related-form suggestions for confirm-first. Metadata fields deliberately
free-form per language (features.md: no hardcoded linguistic rules).

Live probe (4 cases): items, parent links, resolved-sense passthrough, and
per-language metadata all correct on the first draft. One quality iteration:
verb suggestions jumped to the imperfect tense (twice — pronoun and bare form)
before finishing the present. Added: exhaust same-tense persons first; a
pronoun+bare pair is ONE suggestion. After: tu/il/nous present forms first,
imparfait last, no duplicates.

Code-side guard: suggestions duplicating an extracted item token are dropped
deterministically. Goldens: evals/golden/extraction.jsonl.

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

## QUIZ_GENERATION_SYSTEM_V1 + JUDGE_QUIZ_SYSTEM_V1 (2026-07-14)

Drafted together with the judged-retry loop (generate -> judge -> one retry
with the judge's rationale when overall < 4; threshold starts at 4, sub-4
quizzes logged as QUIZ_JUDGE_REJECTED for tuning). Two question formats in one
prompt: mcq (4 choices) and translation (expected_answer).

Live probe findings (3 payloads, Groq/llama-3.3-70b), three iterations:

1. **Doubled article, judge blind to it.** "J'ai passé une très bonne ___" with
   choice "la soirée" -> "une très bonne la soirée". Judge scored it 5/5.
   Fix: substitution check in BOTH prompts (substitute each choice into the
   blank; completed sentence must be grammatical).
2. **Translation tested the wrong word.** user_note "mixes up with soir" seduced
   the generator into expected_answer "le soir" — target token absent. Judge
   caught this one (align=1); retry also failed. Fix: expected_answer MUST
   contain the target item; user_note may shape context, never the answer.
3. **Sense flip, judge blind again.** meaning_note "the evening (time span)"
   produced a party-sense question; judge passed it 5/5. Fix: explicit
   post-write sense verification in the generator + mandatory sense comparison
   in the judge. Final probe: time-span sentence with the target token and a
   party context kept as the trap ("La fête commencera dans la soirée").

**Known ceiling:** a judge on the same free-tier model misses subtle flaws
(sense mismatches, double-defensible tense choices in reported speech). The
offline eval suite should run the judge on a stronger model tier than the
generator. Interview line: "don't let the model grade its own homework at its
own intelligence level."

## GRADING_SYSTEM_V1 (2026-07-14)

Deterministic paths first: MCQ grading never calls an LLM (stored explanation,
correct=q4 recognition / wrong=q1); typed answers get an exact-match fast path
(normalize case/whitespace/punctuation -> q5, zero cost). LLM grades only
non-exact typed answers.

Live probe (7 cases), one iteration:

- PASS first try: fast paths, accent-only mistakes (correct, q4), futur proche
  alternative accepted (the false-negative guard working).
- **FAIL: "dans le soirée" forgiven as an accent issue** (correct, q4) — a
  gender error, often the very thing being tested. Fix: prompt now defines
  accent mistakes as diacritics-only and declares grammar mistakes never
  forgivable, with an explicit article/agreement check step.
- Minor: wrong word scored q2 with confused feedback; now capped at q0-1.
- Accepted leniency: a semantically-shifted but defensible translation is
  graded correct — chosen tradeoff, false negatives hurt more than false
  positives here.

Goldens: evals/golden/quiz_generation.jsonl, evals/golden/grading.jsonl.

## EXTRACTION_SYSTEM V1 -> V2 (2026-07-18)

Production-found (Catherine, live chat on the deployed app): after the
ambiguity question "'never mind', 'too bad', or both?", the answer
"just too bad" was saved as meaning_note "just too bad" — filler included.

Root cause: V1 literally instructed "copy resolved_meaning when given". The
resolved_meaning is a conversational ANSWER, not a clean label; copying was
the wrong contract. Same line made "both" a latent bug: it would have been
copied as a meaning_note instead of producing one item per sense.

V2 change: resolved_meaning is now framed as the user's conversational answer
to "which sense did you mean?", with three rules — distill to a short
dictionary-style sense (drop filler), "both"-type answers emit one item per
sense, never invent an unchosen sense.

Live probe (4 cases): 4/4 on first iteration —
- "just too bad" -> meaning_note "too bad"
- "both" (soirée) -> two items, evening + party
- "I think the second one, the party" -> "party"
- no resolved_meaning (je parle) -> unchanged V1 behaviour (regression)

Known limit, accepted: a bare ordinal answer ("the second one") cannot
resolve, because the extractor never sees the candidate list — the UI only
forwards the user's text. Fix would be passing the ambiguity candidates
through to extraction; deferred until it bites in practice.

Goldens: resolved-meaning-filler / -both / -verbose in
evals/golden/extraction.jsonl.
