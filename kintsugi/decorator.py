"""
Core @heal decorator and in-memory hot-swap engine for KintsugiPy.
"""

from functools import wraps
import inspect
import logging
import sys
import traceback
from typing import Any, Callable, Dict, List, Optional, Type, Union

from kintsugi.cache import PatchCache, compute_fingerprint
from kintsugi.inspector import build_repair_prompt, extract_function_source
from kintsugi.providers import LLMProvider, resolve_provider
from kintsugi.sandbox import compile_and_extract_function, validate_contract

logger = logging.getLogger("kintsugi")


class FunctionState:
    """Holds runtime state, active callable reference, and telemetry for a decorated function."""

    def __init__(self, func: Callable, schema: Optional[Type] = None) -> None:
        self.original_func = func
        self.active_func = func
        self.schema = schema
        self.source_code = extract_function_source(func)
        self.func_name = func.__name__
        self.fingerprint = compute_fingerprint(self.func_name, self.source_code)
        self.is_healed = False
        self.heal_count = 0
        self.last_patch_code: Optional[str] = None


def heal(
    schema: Optional[Type] = None,
    max_retries: int = 3,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 30.0,
    cache_dir: Optional[str] = ".kintsugi_cache",
    chain: Optional[List[Union[dict, LLMProvider]]] = None,
    on_heal: Optional[Callable[[str, str], None]] = None,
) -> Callable:
    """Decorator that empowers Python functions with autonomous self-healing capabilities."""

    def decorator(func: Callable) -> Callable:
        state = FunctionState(func, schema)
        cache = PatchCache(cache_dir)
        is_coroutine = inspect.iscoroutinefunction(func)

        # 1. Cold-start check: Rehydrate from disk cache if a patch already exists
        cached_patch = cache.load_patch(state.func_name, state.fingerprint)
        if cached_patch:
            try:
                # Inherit original function's closure/module globals
                fn_globals = getattr(func, "__globals__", {})
                rehydrated_fn = compile_and_extract_function(
                    cached_patch, state.func_name, fn_globals
                )
                state.active_func = rehydrated_fn
                state.is_healed = True
                state.last_patch_code = cached_patch
                logger.info("[Kintsugi] Rehydrated '%s' from disk cache.", state.func_name)
            except Exception as e:
                # If cached patch is somehow invalid, fallback to original function
                logger.warning("[Kintsugi] Failed to rehydrate '%s' from cache: %s", state.func_name, e)
                state.active_func = func

        # Resolve provider on demand
        def get_provider() -> LLMProvider:
            return resolve_provider(
                provider=provider,
                model=model,
                api_key=api_key,
                base_url=base_url,
                timeout=timeout,
                chain=chain,
            )

        if is_coroutine:
            @wraps(func)
            async def async_wrapper(*args: Any, **kwargs: Any) -> Any:
                # First attempt with active function
                try:
                    result = await state.active_func(*args, **kwargs)
                    return validate_contract(result, schema)
                except Exception as initial_exc:
                    # Enter healing cycle
                    logger.warning(
                        "[Kintsugi] Unhandled exception in '%s': %s. Initiating repair cycle...",
                        state.func_name,
                        initial_exc,
                    )
                    active_provider = get_provider()
                    current_exc = initial_exc
                    fn_globals = getattr(func, "__globals__", {})

                    for attempt in range(1, max_retries + 1):
                        logger.debug(
                            "[Kintsugi] Attempt %d/%d repairing '%s' via %s (%s)",
                            attempt,
                            max_retries,
                            state.func_name,
                            active_provider.__class__.__name__,
                            active_provider.model,
                        )
                        tb_str = "".join(
                            traceback.format_exception(
                                type(current_exc), current_exc, current_exc.__traceback__
                            )
                        )
                        system_prompt, user_prompt = build_repair_prompt(
                            func=func,
                            source_code=state.last_patch_code or state.source_code,
                            exc=current_exc,
                            tb_str=tb_str,
                            args=args,
                            kwargs=kwargs,
                            schema=schema,
                        )

                        try:
                            # 1. Ask LLM for patch
                            patch_code = await active_provider.agenerate_patch(
                                user_prompt, system_prompt
                            )

                            # 2. Compile in sandbox
                            candidate_fn = compile_and_extract_function(
                                patch_code, state.func_name, fn_globals
                            )

                            # 3. Dry-run test with failing inputs
                            raw_result = await candidate_fn(*args, **kwargs)

                            # 4. Validate output contract
                            validated_result = validate_contract(raw_result, schema)

                            # 5. Hot-swap in memory!
                            state.active_func = candidate_fn
                            state.is_healed = True
                            state.heal_count += 1
                            state.last_patch_code = patch_code

                            # 6. Save to cache
                            cache.save_patch(
                                state.func_name,
                                state.fingerprint,
                                patch_code,
                                metadata={
                                    "original_error": str(initial_exc),
                                    "attempts": attempt,
                                    "provider": active_provider.__class__.__name__,
                                    "model": active_provider.model,
                                },
                            )

                            logger.info(
                                "[Kintsugi] Successfully healed and hot-swapped '%s' in memory (attempt %d).",
                                state.func_name,
                                attempt,
                            )

                            if on_heal:
                                on_heal(state.func_name, patch_code)

                            return validated_result

                        except Exception as repair_exc:
                            logger.warning(
                                "[Kintsugi] Attempt %d to heal '%s' failed: %s",
                                attempt,
                                state.func_name,
                                repair_exc,
                            )
                            current_exc = repair_exc
                            if attempt == max_retries:
                                logger.error(
                                    "[Kintsugi] Failed to heal '%s' after %d attempts.",
                                    state.func_name,
                                    max_retries,
                                )
                                raise RuntimeError(
                                    f"Kintsugi failed to heal '{state.func_name}' after {max_retries} attempts. Last error: {str(repair_exc)}"
                                ) from initial_exc

            # Attach metadata
            async_wrapper.__kintsugi_state__ = state
            return async_wrapper

        else:
            @wraps(func)
            def sync_wrapper(*args: Any, **kwargs: Any) -> Any:
                # First attempt with active function
                try:
                    result = state.active_func(*args, **kwargs)
                    return validate_contract(result, schema)
                except Exception as initial_exc:
                    # Enter healing cycle
                    logger.warning(
                        "[Kintsugi] Unhandled exception in '%s': %s. Initiating repair cycle...",
                        state.func_name,
                        initial_exc,
                    )
                    active_provider = get_provider()
                    current_exc = initial_exc
                    fn_globals = getattr(func, "__globals__", {})

                    for attempt in range(1, max_retries + 1):
                        logger.debug(
                            "[Kintsugi] Attempt %d/%d repairing '%s' via %s (%s)",
                            attempt,
                            max_retries,
                            state.func_name,
                            active_provider.__class__.__name__,
                            active_provider.model,
                        )
                        tb_str = "".join(
                            traceback.format_exception(
                                type(current_exc), current_exc, current_exc.__traceback__
                            )
                        )
                        system_prompt, user_prompt = build_repair_prompt(
                            func=func,
                            source_code=state.last_patch_code or state.source_code,
                            exc=current_exc,
                            tb_str=tb_str,
                            args=args,
                            kwargs=kwargs,
                            schema=schema,
                        )

                        try:
                            # 1. Ask LLM for patch
                            patch_code = active_provider.generate_patch(
                                user_prompt, system_prompt
                            )

                            # 2. Compile in sandbox
                            candidate_fn = compile_and_extract_function(
                                patch_code, state.func_name, fn_globals
                            )

                            # 3. Dry-run test with failing inputs
                            raw_result = candidate_fn(*args, **kwargs)

                            # 4. Validate output contract
                            validated_result = validate_contract(raw_result, schema)

                            # 5. Hot-swap in memory!
                            state.active_func = candidate_fn
                            state.is_healed = True
                            state.heal_count += 1
                            state.last_patch_code = patch_code

                            # 6. Save to cache
                            cache.save_patch(
                                state.func_name,
                                state.fingerprint,
                                patch_code,
                                metadata={
                                    "original_error": str(initial_exc),
                                    "attempts": attempt,
                                    "provider": active_provider.__class__.__name__,
                                    "model": active_provider.model,
                                },
                            )

                            logger.info(
                                "[Kintsugi] Successfully healed and hot-swapped '%s' in memory (attempt %d).",
                                state.func_name,
                                attempt,
                            )

                            if on_heal:
                                on_heal(state.func_name, patch_code)

                            return validated_result

                        except Exception as repair_exc:
                            logger.warning(
                                "[Kintsugi] Attempt %d to heal '%s' failed: %s",
                                attempt,
                                state.func_name,
                                repair_exc,
                            )
                            current_exc = repair_exc
                            if attempt == max_retries:
                                logger.error(
                                    "[Kintsugi] Failed to heal '%s' after %d attempts.",
                                    state.func_name,
                                    max_retries,
                                )
                                raise RuntimeError(
                                    f"Kintsugi failed to heal '{state.func_name}' after {max_retries} attempts. Last error: {str(repair_exc)}"
                                ) from initial_exc

            # Attach metadata
            sync_wrapper.__kintsugi_state__ = state
            return sync_wrapper

    return decorator
