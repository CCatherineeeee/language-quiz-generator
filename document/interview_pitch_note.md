# why project

Standard RAG is designed for semantic fact retrieval (e.g., “What time is the meeting in the text?”). Language learning, however, requires syntactic abstraction—abstracting a grammar rule out of a sentence and generating a brand-new scenario to test true comprehension rather than rote memory.

## Regarding automated background worker

Hiring managers love to ask: "How do you stop an LLM from breaking your code when running on an automated background worker?" Your feature description outlines the exact two answers they want to hear:

Temperature = 0.0: Setting the model's temperature to absolute zero eliminates creative randomness. It forces the LLM to behave like a deterministic code module rather than a chatbot.

Structured Outputs (JSON Schema / Tool Calling): By binding the API call to a strict JSON Schema, the LLM physically cannot return conversational fluff like "Sure, here is a quiz for you!". It can only emit valid JSON that matches your exact Pydantic or Spring schema properties.

## logging

When an interviewer asks,"LLMs are unpredictable and background workers are hard to track—how do you know your system is actually running smoothly?"
You get to answer: "I implemented structured JSON logging across my Kafka consumers and bound a tracing context to our LLM gateway. If a background generation task fails, I can immediately correlate the Kafka correlation ID with the raw LLM response payload to diagnose whether it was a schema parsing validation error or an API rate limit."
That answer instantly sets you apart from junior developers who only build synchronous, local-only applications.

# single agent vs multi agent

note: whether we use multiagent or single depends on whether our task is sequential or not. if yes, then single, if parallel then multi? then how to know if our task sequential or not, meanwhile there might be more new features added?
