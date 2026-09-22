"""GPT-6 Sol client and layout-response plumbing.

The active parser uses the internal layout response format to validate model
output, record safe diagnostics, and account for tokens. It does not extract
business fields or accept a user-defined extraction schema.

Must not let a model call raise anything other than `ExtractionCallError`
(with a populated `PageDiagnostic`) out of `_invoke_structured` -- callers
(src/parse.py) depends on that single failure
shape to turn a bad page into a soft error instead of crashing the run. Must
also never let raw provider text, headers, or request/response bodies reach
a `PageDiagnostic` (see src/diagnostics.py's allowlist).

Next: src/parse.py for the caller, or src/diagnostics.py for the
allowlist that keeps diagnostics safe to log/display.
"""

from __future__ import annotations

import os

from dotenv import load_dotenv
from langchain_core.messages import HumanMessage, convert_to_openai_messages
from langchain_openai import ChatOpenAI
from openai import APIStatusError, APIConnectionError

from src import usage as _usage
from src.models import DEFAULT_MODEL, MODEL_RATES
from src.diagnostics import ExtractionCallError, PageDiagnostic, filter_annotations, safe_identifier, token_count

load_dotenv()

MODEL_NAME = DEFAULT_MODEL

class ExtractConfigError(Exception):
    """Raised when the environment isn't configured to call the model. Never hangs."""


def _reasoning_kwargs() -> dict:
    # See docs/MODEL.md: reasoning_effort is a real ChatOpenAI field, but a given
    # gateway's support for it is unverified without a live call.
    effort = os.environ.get("REASONING_EFFORT", "medium").strip()
    return {"reasoning_effort": effort} if effort else {}


def _build_llm(model: str = DEFAULT_MODEL) -> ChatOpenAI:
    if model not in MODEL_RATES:
        raise ExtractConfigError("Unsupported model")
    api_key = os.environ.get("OPENAI_API_KEY")
    if not api_key:
        raise ExtractConfigError("OPENAI_API_KEY is not set")
    base_url = os.environ.get("OPENAI_BASE_URL") or None
    return ChatOpenAI(
        model=model,
        api_key=api_key,
        base_url=base_url,
        **_reasoning_kwargs(),
    )


def _image_message(text: str, image_b64: str, mime: str) -> HumanMessage:
    return HumanMessage(
        content=[
            {"type": "text", "text": text},
            {"type": "image_url", "image_url": {"url": f"data:{mime};base64,{image_b64}"}},
        ]
    )


def _invoke_structured(llm: ChatOpenAI, schema, messages: list, *, call_name: str,
                       diagnostics: list[PageDiagnostic] | None = None,
                       usage_entries: list[dict] | None = None,
                       max_completion_tokens: int | None = None):
    if llm.model_name != DEFAULT_MODEL:
        raise ExtractConfigError("Unsupported model")
    diagnostic = PageDiagnostic(requested_model=safe_identifier(llm.model_name))
    metadata = None
    try:
        # Goes around ChatOpenAI.invoke()/with_structured_output() to the SDK's
        # raw-response client: langchain's normal path discards the HTTP status,
        # headers, and the provider-returned `model`/filter fields this function
        # needs for diagnostics, so the request is built and parsed by hand here.
        kwargs = {"reasoning_effort": llm.reasoning_effort} if llm.reasoning_effort else {}
        if max_completion_tokens is not None:
            kwargs["max_completion_tokens"] = max_completion_tokens
        raw = llm.root_client.chat.completions.with_raw_response.create(
            model=llm.model_name,
            messages=convert_to_openai_messages(messages),
            response_format={"type": "json_schema", "json_schema": {
                "name": schema.__name__, "strict": True, "schema": schema.model_json_schema(),
            }}, **kwargs,
        )
        diagnostic.http_status = raw.status_code
        diagnostic.request_id = next((safe_identifier(raw.headers.get(key)) for key in
            ("x-request-id", "apim-request-id", "x-ms-request-id") if safe_identifier(raw.headers.get(key))), None)
        data = raw.parse().model_dump()
        diagnostic.model = safe_identifier(data.get("model"))
        usage_data = data.get("usage") or {}
        diagnostic.input_tokens = token_count(usage_data.get("prompt_tokens"))
        diagnostic.output_tokens = token_count(usage_data.get("completion_tokens"))
        prompt_details = usage_data.get("prompt_tokens_details") or {}
        diagnostic.cached_tokens = token_count(prompt_details.get("cached_tokens"))
        diagnostic.cache_write_tokens = token_count(prompt_details.get("cache_write_tokens"))
        diagnostic.usage_known = diagnostic.input_tokens is not None and diagnostic.output_tokens is not None
        if usage_data:
            metadata = {"input_tokens": diagnostic.input_tokens, "output_tokens": diagnostic.output_tokens,
                        "input_token_details": {"cache_read": diagnostic.cached_tokens,
                                                "cache_write": diagnostic.cache_write_tokens}}
        for item in data.get("prompt_filter_results") or []:
            if isinstance(item, dict):
                diagnostic.filters.extend(filter_annotations(item.get("content_filter_results"), "prompt"))
        choices = data.get("choices") or []
        if not choices:
            raise ExtractionCallError(diagnostic)
        choice = choices[0]
        finish = choice.get("finish_reason")
        if finish in ("stop", "length", "content_filter", "tool_calls", "function_call"):
            diagnostic.finish_reason = finish
        diagnostic.filters.extend(filter_annotations(choice.get("content_filter_results"), "completion"))
        message = choice.get("message") or {}
        # Order matters: a content-filtered completion can still report
        # finish_reason="stop", so the filter/refusal checks have to run
        # before the generic "didn't finish cleanly" (`finish != "stop"`)
        # check, or a filtered response would be misclassified as "incomplete".
        if finish == "content_filter" or any(f.filtered for f in diagnostic.filters):
            diagnostic.outcome = "content_filtered"
        elif message.get("refusal"):
            diagnostic.outcome = "refused"
        elif finish != "stop":
            diagnostic.outcome = "incomplete"
        else:
            result = schema.model_validate_json(message.get("content") or "")
            diagnostic.outcome = "parsed"
            return result
        raise ExtractionCallError(diagnostic)
    except APIStatusError as exc:
        diagnostic.http_status = exc.status_code
        diagnostic.request_id = safe_identifier(exc.request_id)
        body = exc.body if isinstance(exc.body, dict) else {}
        error = body.get("error", body)
        error = error if isinstance(error, dict) else {}
        inner = error.get("innererror", error.get("inner_error", {}))
        inner = inner if isinstance(inner, dict) else {}
        diagnostic.filters.extend(filter_annotations(inner.get("content_filter_results"), "prompt"))
        diagnostic.outcome = "content_filtered" if error.get("code") == "content_filter" or any(f.filtered for f in diagnostic.filters) else "http_error"
        raise ExtractionCallError(diagnostic) from None
    except APIConnectionError:
        diagnostic.outcome = "transport_error"
        raise ExtractionCallError(diagnostic) from None
    except ExtractionCallError:
        raise
    except Exception:
        # Catch-all: anything not already mapped above (e.g. schema
        # validation failing on well-formed-but-wrong-shape JSON, or an SDK
        # error this function doesn't otherwise special-case) becomes a
        # generic "invalid_response" outcome rather than an unhandled
        # exception, so one bad page can't crash the whole document run.
        diagnostic.outcome = "invalid_response"
        raise ExtractionCallError(diagnostic) from None
    finally:
        # Runs on every path, success or failure, so a failed call's (partial
        # or absent) usage is still recorded -- usage_known distinguishes a
        # genuinely-zero count from a truly unreported one, rather than
        # letting a failed call look free.
        _usage.record(call_name, DEFAULT_MODEL, metadata,
                      usage_known=diagnostic.usage_known, entries=usage_entries)
        if diagnostics is not None:
            diagnostics.append(diagnostic)
