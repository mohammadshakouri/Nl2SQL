"""
LLM I/O for the Spider evaluation.

One streamed completion -> one ``LLMCall`` record carrying everything worth
logging about it: the raw text, why it stopped, token usage, latency and, when
the call failed, the error. ``call_llm`` never raises for API errors, so a
failed call is data (it is written to the run log) rather than a crash.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

import app.dotenv as env
from app.nl2sql_chain import NL2SQLChain, get_llm_settings

# Set to False the first time the endpoint rejects ``stream_options``, so the
# run continues (without token usage) instead of failing every call.
_include_usage = True


@dataclass
class LLMCall:
    """Outcome of one streamed completion."""
    provider: str
    model: str
    text: str = ""
    finish_reason: Optional[str] = None
    usage: Optional[Dict] = None
    """Token usage exactly as the provider reported it (None if not reported)."""
    latency_ms: float = 0.0
    ttft_ms: Optional[float] = None
    """Time to the first content token."""
    error: Optional[str] = None
    error_type: Optional[str] = None


def describe_exc(exc: BaseException) -> str:
    """Exception type + message; some (e.g. httpx timeouts) have an empty str()."""
    message = str(exc).strip() or repr(exc)
    return f"{type(exc).__name__}: {message}"


def _usage_to_dict(usage) -> Optional[Dict]:
    if usage is None:
        return None
    if isinstance(usage, dict):
        return usage
    dump = getattr(usage, "model_dump", None)
    if callable(dump):
        return dump(exclude_none=True)
    return {k: v for k, v in vars(usage).items() if v is not None}


def token_counts(usage: Optional[Dict]) -> Dict[str, int]:
    """Flatten a provider usage dict into the counters the run summary adds up."""
    usage = usage or {}
    prompt = usage.get("prompt_tokens")
    completion = usage.get("completion_tokens")
    total = usage.get("total_tokens")
    if total is None and prompt is not None and completion is not None:
        total = prompt + completion
    reasoning = (usage.get("completion_tokens_details") or {}).get("reasoning_tokens")
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens")
    counts = {
        "prompt_tokens": prompt,
        "completion_tokens": completion,
        "total_tokens": total,
        "reasoning_tokens": reasoning,
        "cached_tokens": cached,
    }
    return {k: v for k, v in counts.items() if isinstance(v, int)}


async def call_llm(messages: list) -> LLMCall:
    """Stream one completion for ``messages`` and return everything observed."""
    global _include_usage
    settings = get_llm_settings()
    call = LLMCall(provider=settings.provider, model=settings.model)
    parts: List[str] = []
    started = time.perf_counter()

    def note_content(text: str) -> None:
        if call.ttft_ms is None:
            call.ttft_ms = (time.perf_counter() - started) * 1000
        parts.append(text)

    try:
        if env.use_local_llm:
            stream = await NL2SQLChain.generate_sql_ollama(messages, stream=True)
            async for chunk in stream:
                message = getattr(chunk, "message", None)
                if message is not None and getattr(message, "content", None):
                    note_content(message.content)
                if getattr(chunk, "done", False):
                    call.finish_reason = getattr(chunk, "done_reason", None)
                    prompt = getattr(chunk, "prompt_eval_count", None)
                    completion = getattr(chunk, "eval_count", None)
                    if prompt is not None or completion is not None:
                        call.usage = {
                            "prompt_tokens": prompt,
                            "completion_tokens": completion,
                        }
                    break
        else:
            try:
                stream = await NL2SQLChain.generate_sql_openai(
                    messages, stream=True, include_usage=_include_usage
                )
            except Exception as exc:
                if _include_usage and _rejects_stream_options(exc):
                    _include_usage = False
                    stream = await NL2SQLChain.generate_sql_openai(
                        messages, stream=True, include_usage=False
                    )
                else:
                    raise
            # Do not stop at finish_reason: with include_usage the token usage
            # arrives in one more chunk after the last content chunk.
            async for chunk in stream:
                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    call.usage = _usage_to_dict(usage)
                if not chunk.choices:
                    continue
                choice = chunk.choices[0]
                if choice.delta and choice.delta.content:
                    note_content(choice.delta.content)
                if choice.finish_reason is not None:
                    call.finish_reason = choice.finish_reason
    except Exception as exc:
        call.error = describe_exc(exc)
        call.error_type = type(exc).__name__

    call.text = "".join(parts)
    call.latency_ms = (time.perf_counter() - started) * 1000
    return call


def _rejects_stream_options(exc: Exception) -> bool:
    text = str(exc).lower()
    return "stream_options" in text or "include_usage" in text


async def preflight() -> LLMCall:
    """
    One tiny completion with the exact provider/model/parameters of the run.

    Run before a paid evaluation so a wrong model name, key, base URL or
    unsupported parameter fails here, not after a thousand failed samples.
    """
    return await call_llm(
        [{"role": "user", "content": "Reply with exactly the single word: OK"}]
    )
