"""LLM provider abstraction: one `Provider.complete(system, user, model)` interface
(llm/base.py) behind four concrete clients (Ollama, Agnes AI, generic OpenAI-compatible,
Gemini), enumerated in llm/registry.py so callers can select a provider by name. This
package must not embed any agent-loop logic (rewrite/critique/citation rules) -- that
belongs in agent/. Start reading at llm/base.py, then llm/registry.py.
"""
