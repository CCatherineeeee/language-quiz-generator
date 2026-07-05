# Before features, why

Most app in market right now are just simple knowledge checking, such as anki, or Google Notebook. My language using experience with google notebook wasn't as good as I thought. When I upload my french textbook, the app generate quizes such as "where are the two characters at" or like "when are they meeting" this type of question instead of language question. I know it's mainly for other wild range of textbook knowledge checking and RAG, but not quite suitale for my language studying. After prompting, the quiz is still stuck to the example sentence already in the textbook, testing my memory instead of testing whether I can really utilize those gramma points. Plus, google notebook don't have a space repitition (at least when I was using it), which is something I think quite important for learning new language. Thus, I want to build this app.

# Features

## User Input Intent and Metadata Extraction Pipeline (P0)

### The Analysis Layer: Grammar & Ambiguity (P0)

- checking user input for spelling and grammar mistake, if so, response to user with correction
- **analyze whether user's input is ambiguous or not. For example, if user is adding a new word soirée, which has both meaning of night and party, is user meaning they learnt one of the meaning or both.**
- ensure LLM returns a strictly structured schema (using Pydantic). If is_ambiguous evaluates to true, backend should immediately short-circuit the normal response loop and trigger a clarification UI widget for the user instead of guessing.

### The Linguistic Meta-Extractor: Input Enhancement (P0)

- Enhance user's input. For example, if use input a verb only, should check if user know about the conjugations; similarly: noun -> singular, plural, sexuality; adj -> sexuality conjugation; and many 固定搭配 related. Should build a rule for this based on user's preference and language's nature (e.g. noun sexuality doesn't exist for all language)
- Engineering Critique: Do not hardcode linguistic rules (like "if noun, check gender") into your backend application code. Different languages have entirely different syntactic structures (e.g., French has grammatical gender; Chinese does not, but has measure words).
- Let the LLM handle the schema abstraction dynamically. Have the pipeline output a generic `linguistic_metadata` JSON object.
  - For soirée, it extracts: {"part_of_speech": "noun", "gender": "feminine", "plural": "soirées"}.
  - For a verb, it extracts the infinitive and base tense.
    Your system then saves this structured metadata to the user's vocabulary profile automatically.

### Guardrails & The Profanity Edge Case (P1)

- Basic guardrail, such as rate limitor, length detection, should be applied to protect the server and llm api. But when user say something which will normally be filtered, such as sh*t f*ck, should we directly filter or ask user to clarify what they mean? This will be fun, and can be a good to have.
- Separate infrastructure-level guardrails from content-level guardrails. Rate limiting and length detection must happen at your API Gateway level (e.g., using Redis or FastAPI middleware) to save money. Never let an LLM process an oversized or spammed request just to tell you it's too long.
- Let the input like sht* or fck* via a rigid regex block pass through, and use the LLM to classify the intent sentiment.
  - If the intent is malicious/abuse (insulting the bot), trigger a standard 400 error or a polite deflection.
    -- If the intent is expressive/learning (e.g., "I had a fcking great day" or "How do I say 'this is sht' in French?"), use it as a teaching moment. Have the agent explain the target language's equivalent vulgarity or slang level (e.g., explaining the register of putain or merde in French).

## User input storage (P0)

- After "Input Intent and Metadata Extraction Pipeline", store user's learnt knowlege item, either a word, a sentence phrase, a gramma, etc, into the database
- For details, see planning.md's Data schema section.

## User review data retrieve (P0)

- An async worker will generate quiz problem asynchrounously. This worker need to know items that are due today `SELECT entity_id FROM user_mastery_matrix WHERE user_id = 5 && next_review_date <= NOW()`. We should provide this raw list of due IDs
- For details, see planning.md's Data schema section.

## User profile retrieve and analysis (P2)

- Tracks the user's current proficiency, vocabulary size, past mistakes, and what should be reviewed today based on SM-2 algo.
- Data Inputs
- Output: A structured JSON object representing the user’s exact current "state" (e.g., CEFR level: A2, weak on past tense verbs, strong on food vocabulary).

## The Linguistic Recommendation (P2)

- Based on user's progress, recommend next new linguistic (words, gramma, phrases) for user to study
- The purpose is to expand on new knowledge, different with reinforce exisiting knowledge
- Tools: Retrieval-Augmented Generation (RAG) tied to a vector database of curated language resources, or a search tool to fetch real-world content (like news articles at a specific reading level).

# Quiz generator (P0)

- generate based on result from "User review data retrieve"
- an event-driven, asynchronous background worker pipeline
- Generating balanced, pedagogically sound questions requires strict temperature controls and structured output (JSON schema validation). It needs to focus entirely on formatting a proper quiz without worrying about conversational fluff.
- Eager Generation: When user inputing for what they newly learn, should also try to trigger an asynchronously call to generate quiz on new add item, in order to save response time later. Might use an event queue to handle this.
- Q: How do you stop an LLM from breaking your code when running on an automated background worker?:
- A:

1. Structured Outputs (JSON Schema / Tool Calling): the primary guarantee. By binding the API call to a strict JSON Schema, the LLM cannot return conversational fluff like "Sure, here is a quiz for you!". It can only emit valid JSON that matches your exact Pydantic schema, and anything that fails validation is rejected and retried.
2. Low temperature (e.g. 0.0–0.2): reduces output variance so quiz formats stay consistent. Note: temperature 0 does NOT make inference deterministic — GPU batching and floating-point effects still produce run-to-run variation. Correctness comes from the schema constraint plus validation, never from temperature alone.

# Quiz collapse preprocessing (P2)

- While looking at that raw list, collapse items are just different versions of the exact same verb (like je parle, tu parles, and nous parlons). Tell the AI: "Hey, these items are all variations of a verb (e.g. 'parler'). Write a single short paragraph story where the user has to fill in the blanks for all 3 variations at once."

# SM-2 update (P0)

- When quiz ended, should generate and user result. Update SM-2 data based on result

# Quiz result analyze (P2)

- When quiz ended, should return problem and user result to chat interface, and redirect user back to chat interface. Indicating on interface that we are walkthough through problem evaluation in this interface
- answers user questions on explaining gramma points ("Why did I use en instead of dans here?")
- could be used in chat interface, and wrong-problem-walkthrough-review phrase.
- finds articles, videos, or grammar explanations tailored to the user's weak points.
- while explaning, point out the main testing knowledge point no matter if user get it correct or not, just to reinforce menory. If necessary, connect this knowledge point with some other related knowledge. 举一反三.
- Good to have: a more interactive interface。prototype：每一个题目用卡片形式展现，要展示用户回答 or / and 正确答案,且可以让用户继续提问

# AI output Evaluation (P1)

## Eval Report as a Public Artifact (P1)

- Publish the golden-dataset scores in the README as an auto-generated table: per-category scores (target alignment, linguistic authenticity, distractor validity) and the grading false-negative rate, stamped with date, model version, and prompt version. The CI eval run regenerates it.
- Why: "LLM-as-judge" is a claim on every resume now; a table of real numbers tied to prompt versions is proof, and almost no portfolio project publishes one.
- Good to have (P2): a small in-app /evals dashboard showing score history across prompt versions.

## Quiz Generation Evaluation (P1)

The Judge reviews a sample of generated quizzes before or during production staging.

- Target Alignment: Does the quiz actually test the exact token and type requested? (e.g., If requested "la soirée", did it accidentally test "le soir"?)
- Linguistic Authenticity: Is the generated French sentence natural and grammatically flawless?
- Distractor Validity: Are the incorrect multiple-choice options (distractors) grammatically plausible, or are they obvious gibberish?

## Grading Accuracy Evaluation (P1)

To prevent the app from frustrating users by marking correct answers as wrong, we run offline evaluation on the grading prompt.

- Strict Adherence: Did the grading LLM correctly follow the semantic rules?
- False Negative Rate: How often did the LLM mark a valid alternative answer or an answer with a minor whitespace issue as completely incorrect?

### Strategy 1: The Offline "Golden Dataset" (Regression Testing) (P1)

During development, we maintain a static Golden Dataset—a curated list of 100+ perfect, human-verified pairs of inputs and expected outputs (e.g., a known user input, the expected correct grade, and a perfect explanation).
Whenever we tweak our system prompts or switch to a cheaper/faster model, we run the entire Golden Dataset through the new setup.
The Evaluation Judge model compares the new outputs against the human-verified outputs and scores them from 1 to 5 using a structured framework (like G-Eval).
Success Metric: The code cannot be deployed to production unless the automated evaluation score maintains a threshold of greater than 4.5/5 across the test suite.

### Strategy 2: Online Shadow Sampling (Production Monitoring) (P2)

In production, we don't want to run a second LLM call on every single user interaction because it would double our API costs. Instead, we use our event-driven architecture to sample data asynchronously.
The app processes a quiz and updates a user's matrix normally.
An event listener randomly selects 5% of all generated quizzes and gradings and publishes them to an evaluation queue.
The Judge LLM reviews this 5% sample completely off-screen, flagging any failures (e.g., scoring an item as a 1 or 2 on accuracy).
If a failure is flagged, the system sends an alert or saves it to an internal dashboard for manual review, allowing us to catch prompt drift early.

# App Observe (logging) (P0)

## The LLM Payload Log (The AI Context) (P0)

You must capture the exact prompt sent out and the exact raw string returned before your system tries to parse it into Java/Python objects.
Why: If your code crashes with a JSONParseException, you need to look at the logs to see if the LLM hallucinated a trailing comma, added a markdown fence (json ... ), or cut off mid-sentence because it ran out of tokens.

## The Queue Event Lifecycle Log (The Async Chain) (P0)

Log when an event enters the queue and when a worker successfully picks it up and finishes it.
Why: If a user adds a word and the quiz never generates, you need to track where the chain snapped. Did the producer fail to publish NEW_ITEM_ADDED, or did the consumer crash while processing it?

## The SM-2 Math Log (The State Change) (P1)

Log the input quality and the resulting interval changes during card grading.
Why: If a user complains that a word they got right is appearing again 5 minutes later, you need a single log line showing: User 5, Entity 102: q=5 -> Old Interval: 1, New Interval: 6. If the database shows an interval of 1, you know your math formula or your DB update query has a bug.

# Delivery & Deployment

## CI Pipeline: GitHub Actions (P2)

- On every push: lint + unit tests (SM-2 math, Pydantic schema validation) must pass before merge.
- Extension: run the golden-dataset eval suite as a deploy gate — deployment is blocked unless the eval score stays above the 4.5/5 threshold (see AI output Evaluation).
- Until CI exists: run the eval suite locally before each deploy and commit the regenerated README score table, so the eval-gated-deploy discipline holds manually.

## Live Demo Deployment (P1)

- Deploy to a managed platform with a public URL. Platform TBD; requirement is always-on hosting so a recruiter clicking the link gets an instant load, no cold start.
- Pre-seeded demo account: the reviewer lands in an account that already has vocabulary, due items, and a ready quiz. Never show an empty state.
- Cost protection: infrastructure-level rate limiting (see Guardrails) plus a hard monthly spend cap on the LLM API key, since public visitors trigger real LLM calls.
