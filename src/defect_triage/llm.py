"""Single LLM entry point, Langfuse-instrumented.

WHY THIS FILE EXISTS
--------------------
Several nodes in the pipeline (Localizer, Patch-writer, Critic) need to talk to a
large language model. Instead of letting each node call the model API directly, we
funnel *every* call through the one function in this file. That gives us two things:

  1. Observability: every call is automatically wrapped in a Langfuse "span", so we
     can see it in the Langfuse dashboard (CLAUDE.md section 6 forbids untraced calls).
  2. One place to change: model name, provider, temperature, retries — all live here.

"""

from __future__ import annotations

from typing import Any

from dotenv import load_dotenv  # reads key=value pairs from the .env file
from langfuse import get_client  # Langfuse tracing client (provider-agnostic)
from openai import OpenAI  # the OpenAI SDK

import os

# Pull secrets from .env into the process environment *once*, at import time, so
# that OPENAI_API_KEY and the LANGFUSE_* keys are available before we build any
# client below. load_dotenv() does nothing if the variables are already set.
load_dotenv()

# Which model to call. We read it from the OPENAI_MODEL env var so it can be changed
# without editing code; "gpt-4o" is the fallback if the var is not set.
DEFAULT_MODEL = os.getenv("OPENAI_MODEL", "gpt-4o")

# Module-level cache for the OpenAI client. It starts as None and is created on first
# use (see _client below). Caching avoids rebuilding the client on every call.
_openai_client: OpenAI | None = None


def _client() -> OpenAI:
    """Return the OpenAI client, creating it the first time it is needed.

    This "lazy initialization" matters: building ``OpenAI()`` reads OPENAI_API_KEY,
    so if we built it at import time, simply importing this module would require a
    key. By deferring it to the first real call, importing llm.py stays key-free
    (handy for tests that mock the client). The leading underscore marks it private.
    """
    global _openai_client  # we assign to the module-level variable, so declare it global
    if _openai_client is None:  # first call only
        _openai_client = OpenAI()  # reads OPENAI_API_KEY from the environment
    return _openai_client


def complete(
    messages: list[dict],
    *,  # everything after this must be passed by keyword (e.g. node="..."), not by position
    node: str,
    instance_id: str,
    retry_count: int = 0,
    model: str | None = None,
    temperature: float = 0.0,
    **kwargs: Any,  # any extra options (e.g. max_tokens) are forwarded to the API untouched
) -> str:
    """Send a chat-completion request and return the assistant's text.

    The call is wrapped in a Langfuse "generation" span named after ``node`` and
    tagged (via metadata) with ``node``, ``instance_id``, and ``retry_count`` so the
    whole pipeline run is observable. Token usage is recorded when the API returns it.

    Args:
        messages: OpenAI-style chat messages, e.g. ``[{"role": "user", "content": ...}]``.
        node: Logical label for this call; becomes the Langfuse span name
            (e.g. "extract_terms", "rank_candidates").
        instance_id: SWE-bench instance this call belongs to, for trace grouping.
        retry_count: Pipeline retry counter, recorded for debugging self-correction.
        model: Override the default model (defaults to ``OPENAI_MODEL`` or "gpt-4o").
        temperature: Sampling temperature; 0.0 for deterministic localization.
        **kwargs: Passed through to ``chat.completions.create`` (e.g. ``max_tokens``).

    Returns:
        The assistant message content as a string (empty string if the model
        returned no content).
    """
    # Fall back to the default model unless the caller explicitly overrode it.
    model = model or DEFAULT_MODEL

    # --- API-compatibility shims for newer OpenAI models -----------------------
    # GPT-5-class and the o-series reasoning models changed two things versus the
    # gpt-4o-era Chat Completions API, and nodes were written against the old API:
    #   1. `max_tokens` was renamed to `max_completion_tokens`. The new name is also
    #      accepted by gpt-4o, so we rename unconditionally — safe for every model.
    #   2. They only accept the default sampling temperature and 400 on any explicit
    #      `temperature` other than 1. We therefore drop the temperature for those
    #      model families and keep passing it for the older ones (where 0.0 matters
    #      for deterministic localization).
    if "max_tokens" in kwargs:
        kwargs["max_completion_tokens"] = kwargs.pop("max_tokens")
    fixed_temperature_only = model.startswith(("gpt-5", "o1", "o3", "o4"))
    if not fixed_temperature_only:
        kwargs["temperature"] = temperature

    # Grab the shared Langfuse client. If no Langfuse keys are configured, this
    # returns a disabled client and the span below simply does nothing (no crash).
    langfuse = get_client()

    # Open a tracing span around the whole API call. Using it as a context manager
    # (`with ... as generation`) means the span automatically starts here and is
    # closed when the block ends — even if the API call raises an exception.
    #   - name:     what shows up as the span title in the Langfuse UI
    #   - as_type:  "generation" is Langfuse's span type specifically for LLM calls
    #   - input:    the prompt we sent (logged for inspection)
    #   - model:    recorded so the dashboard knows which model produced this
    #   - metadata: free-form tags; this is how node/instance_id/retry_count are attached
    with langfuse.start_as_current_observation(
        name=node,
        as_type="generation",
        input=messages,
        model=model,
        metadata={
            "node": node,
            "instance_id": instance_id,
            "retry_count": retry_count,
        },
    ) as generation:
        # The actual model call. _client() gives us the cached OpenAI client.
        response = _client().chat.completions.create(
            model=model,
            messages=messages,
            **kwargs,  # temperature / max_completion_tokens normalized above
        )

        # The SDK returns a list of choices; we use the first. ".content" can be None
        # (e.g. if the model only made a tool call), so "or ''" guards against that.
        text = response.choices[0].message.content or ""

        # Record how many tokens the call used, when the API reports it. This makes
        # cost/usage visible per span in Langfuse. Some responses omit usage, so we
        # only attach it when present; otherwise we just record the output text.
        usage = getattr(response, "usage", None)
        if usage is not None:
            generation.update(
                output=text,
                usage_details={
                    "input": usage.prompt_tokens,
                    "output": usage.completion_tokens,
                    "total": usage.total_tokens,
                },
            )
        else:
            generation.update(output=text)

    # The span is now closed (the `with` block ended). Return just the text so callers
    # don't have to know anything about the OpenAI response object's structure.
    return text


# Spec-parity alias: the Day 2 task names this entry point ``claude(...)``. Pointing
# the name ``claude`` at ``complete`` means existing references to claude() keep
# working after the OpenAI switch — same function, same signature, just two names.
claude = complete


def flush() -> None:
    """Force-send any buffered Langfuse spans immediately.

    Langfuse batches spans in the background and sends them periodically. A short-
    lived CLI process can exit before that happens, losing the trace. Calling
    ``flush()`` once at the very end of a run guarantees everything is delivered.
    """
    get_client().flush()
