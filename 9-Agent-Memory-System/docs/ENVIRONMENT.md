# Environment Variables

Names only — no real values here, and this project does not create or load
a `.env` file (writing one is blocked by this workstation's permission
rules; it also reads credentials from the real Windows environment, not a
project file). Set real values with `setx NAME value`, then relaunch your
terminal/agent host so it inherits them.

| Name | Used for |
|---|---|
| `OLLAMA_API_KEY` | Ollama, only if your instance requires auth (local default: none) |
| `AGNESAI_API_KEY` | Agnes AI — `https://apihub.agnes-ai.com/v1`, model `agnes-2.5-flash` |
| `OPENAI_API_KEY` | OpenAI-compatible provider — `gpt-5.6-luna` / `gpt-5.6-terra` |
| `OPENAI_BASE_URL` | Base URL for the OpenAI-compatible provider |
| `GOOGLE_API_KEY` | Gemini — `gemini-3.5-flash-lite` / `gemini-3.7-flash` |

Consumed in Phase 8 by `src/memory/providers.py` via
`config.available_providers()`.
