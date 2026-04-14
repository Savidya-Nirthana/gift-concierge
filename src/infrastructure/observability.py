"""
Observability layer - Langfuse

"""


from loguru import logger
import os
from typing import Optional

_ENABLED: Optional[bool] = None

def _is_enabled() -> bool:
    """Check if Langfuse is enabled"""
    global _ENABLED
    if _ENABLED is not None:
        return _ENABLED

    try:
        from infrastructure.config import _get_nested, _PARAMS
        _ENABLED = _get_nested(_PARAMS, "observability","enabled", default=True)
    except Exception as e:
        _ENABLED = True
    return _ENABLED

_langfused_client = None
_initialized = False

def get_langfuse():
    global _langfused_client, _initialized
    if _initialized:
        return _langfused_client

    _initialized = True

    if not _is_enabled():
        logger.info("Observability disabled via config — LangFuse not initialised.")
        return None

    secret_key = os.getenv("LANGFUSE_SECRET_KEY")
    public_key = os.getenv("LANGFUSE_PUBLIC_KEY")
    host = os.getenv("LANGFUSE_BASE_URL")

    if not secret_key or not public_key:
        logger.warning(
            "LangFuse keys not set (LANGFUSE_SECRET_KEY / LANGFUSE_PUBLIC_KEY). "
            "Tracing is disabled."
        )
        return None

    try:
        from langfuse import Langfuse

        _langfused_client = Langfuse(
            secret_key=secret_key,
            public_key=public_key,
            host=host,
        )
        logger.info(f"Langfuse initialised successfully (host = {host}).")
        return _langfused_client

    except Exception as e:
        logger.error(f"Failed to initialise Langfuse: {e}")
        return None



def fetch_prompt(
    name: str,
    *,
    fallback: str,
    cache_ttl_seconds: int = 300,
    **compile_vars: str,

)-> str:
    client = get_langfuse()

    if client is not None:
        try:
            prompt_obj = client.get_prompt(
                name,
                type="text",
                cache_ttl_seconds=cache_ttl_seconds
            )
            compiled = prompt_obj.compile(**compile_vars) if compile_vars else prompt_obj.compile()
            logger.info(f"Prompt '{name}' fetched and compiled.")
            return compiled
        except Exception as e:
            logger.warning(f"Failed to fetch prompt '{name}': {e}")
    
    if compile_vars:
        return fallback.format(**compile_vars)
    return fallback


try:
    from langfuse import observe as _if_observe
    from langfuse import get_client as _get_lf_client   

except ImportError:
    _if_observe = None
    _get_if_client = None
    logger.debug("Langfuse not installed, observability disabled.")

def observe(
    *,
    name: Optional[str] = None,
    as_type: Optional[str] = None,
): 
    def _noop_decorator(fn):
        return fn
    
    if not _is_enabled() or _if_observe is None:
        return _noop_decorator

    kwargs = {}
    if name is not None:
        kwargs["name"] = name
    if as_type is not None:
        kwargs["as_type"] = as_type

    return _if_observe(**kwargs)


# ---------------------------------------------------------------------------
# Trace & Span Update Helpers (v3 API — uses get_client())
# ---------------------------------------------------------------------------


def update_current_trace(
    *,
    user_id: Optional[str] = None,
    session_id: Optional[str] = None,
    metadata: Optional[dict] = None,
    tags: Optional[list] = None,
) -> None:
    """
    Update the current LangFuse trace with user/session info.

    Safe to call even when tracing is disabled (no-op).
    """
    if _get_lf_client is None or not _is_enabled():
        return
    try:
        client = _get_lf_client()
        kwargs = {}
        if user_id is not None:
            kwargs["user_id"] = user_id
        if session_id is not None:
            kwargs["session_id"] = session_id
        if metadata is not None:
            kwargs["metadata"] = metadata
        if tags is not None:
            kwargs["tags"] = tags
        client.update_current_trace(**kwargs)
    except Exception as exc:
        logger.debug("update_current_trace failed (non-critical): {}", exc)


def update_current_observation(
    *,
    input: Optional[str] = None,
    output: Optional[str] = None,
    metadata: Optional[dict] = None,
    usage: Optional[dict] = None,
    model: Optional[str] = None,
) -> None:
    """
    Update the current span/generation with I/O and usage data.

    In LangFuse v3:
    - Generation updates use ``update_current_generation()`` with
      ``model``, ``usage_details``, ``cost_details``.
    - Span updates use ``update_current_span()`` (no model/usage).

    This helper auto-detects which to call based on whether
    ``model`` or ``usage`` are provided.

    Safe to call even when tracing is disabled (no-op).
    """
    if _get_lf_client is None or not _is_enabled():
        return
    try:
        client = _get_lf_client()

        # If model or usage provided → generation update
        if usage is not None or model is not None:
            gen_kwargs = {}
            if input is not None:
                gen_kwargs["input"] = input
            if output is not None:
                gen_kwargs["output"] = output
            if metadata is not None:
                gen_kwargs["metadata"] = metadata
            if model is not None:
                gen_kwargs["model"] = model
            if usage is not None:
                # v3 uses usage_details (input, output, total)
                gen_kwargs["usage_details"] = usage
            try:
                client.update_current_generation(**gen_kwargs)
                return
            except Exception:
                pass

        # Otherwise → span update
        span_kwargs = {}
        if input is not None:
            span_kwargs["input"] = input
        if output is not None:
            span_kwargs["output"] = output
        if metadata is not None:
            span_kwargs["metadata"] = metadata
        if span_kwargs:
            client.update_current_span(**span_kwargs)
    except Exception as exc:
        logger.debug("update_current_observation failed (non-critical): {}", exc)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def flush() -> None:
    """Flush pending LangFuse events (call before program exit)."""
    if _get_lf_client is not None and _is_enabled():
        try:
            client = _get_lf_client()
            client.flush()
            logger.debug("LangFuse flushed.")
        except Exception as exc:
            logger.debug("LangFuse flush failed: {}", exc)