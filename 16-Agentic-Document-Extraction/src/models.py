"""Model catalog: the only model ids this project will send a request for
(`MODEL_RATES` keys), and their USD-per-million-token pricing estimates. See
docs/MODEL.md for how these rates are used and their caveats (estimates, not
gateway billing data).

Must not: silently fall back to a default for an unrecognized model id --
src/llm.py's `_build_llm` and src/parse.py's `parse_document` both raise
instead (there is no automatic model fallback, see README.md).

Next: src/usage.py, which turns these rates into a session cost estimate.
"""

DEFAULT_MODEL = "gpt-6-sol"

# USD per million tokens: input, cached input, cache write, output.
MODEL_RATES = {
    DEFAULT_MODEL: (2.00, 0.20, 2.50, 10.00),
}
