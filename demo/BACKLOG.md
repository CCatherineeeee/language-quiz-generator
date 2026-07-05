# Backlog — future ideas

## Conversation history carried to the fallback LLM
**Status: implemented for chat; hardening ideas below.**

Today, when the LLM provider switches mid-request (e.g. Groq quota → Gemini), the
*entire* request is re-sent to the next provider. For the Chat tab that means the whole
conversation (rebuilt from `demo_chat_messages` every turn) goes to the new provider, so
it keeps full context. A system message announces the switch in the chat.

Possible hardening later:
- Summarize/trim very long histories before resend (token budget per provider differs).
- Persist which provider answered each turn (currently only in `demo_llm_calls`), and
  show it subtly in the UI.
- Handle a provider that switches *mid-stream* once streaming is added.

## Other ideas
- Real audio for listening/speaking (TTS files + mic STT) instead of browser TTS.
- Let the chat agent also *generate a targeted exercise* on request ("quiz me on what
  we just covered").
- De-duplicate concepts when the agent picks different codes/kinds for the same word.
- Export progress (known concepts + review schedule) to CSV.
