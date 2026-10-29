"""
Core @heal decorator and in-memory hot-swap engine for KintsugiPy.
Includes Thundering Herd concurrency prevention (Double-Checked Locking),
rich observability telemetry (HealReport with unified diffs),
propose-only enterprise mode, custom validation predicates,
and dry-run timeout protection.
"""

import asyncio
from dataclasses import dataclass
import difflib
from functools import wraps
import inspect
import logging
from pathlib import Path
import sys
import threading
import time
import traceback
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    ParamSpec,
    Type,
    TypeVar,
    Union,
)

from kintsugi.cache import PatchCache, compute_fingerprint
from kintsugi.inspector import build_repair_prompt, extract_function_source
from kintsugi.privacy import redact_sensitive_text
from kintsugi.providers import LLMProvider, resolve_provider
from kintsugi.sandbox import (
    compile_and_extract_function,
    execute_with_timeout,
    validate_contract,
)

logger = logging.getLogger("kintsugi")

P = ParamSpec("P")
R = TypeVar("R")


class ProposedPatchError(RuntimeError):
    """Raised in mode='propose' when an autonomous repair is validated and proposed for human review."""

    def __init__(self, message: str, report: "HealReport") -> None:
        super().__init__(message)
        self.report = report


@dataclass
class HealReport:
    """Contains comprehensive telemetry and unified diff for an autonomous repair event."""

    func_name: str
    error_type: str
    error_message: str
    traceback: str
    original_code: str
    healed_code: str
    diff: str
    attempts: int
    provider: str
    model: str
    timestamp: float = 0.0

    @classmethod
    def create(
        cls,
        func_name: str,
        initial_exc: Exception,
        tb_str: str,
        original_code: str,
        healed_code: str,
        attempts: int,
        provider: str,
        model: str,
    ) -> "HealReport":
        diff_lines = list(
            difflib.unified_diff(
                original_code.splitlines(keepends=True),
                healed_code.splitlines(keepends=True),
                fromfile=f"a/{func_name}.py",
                tofile=f"b/{func_name}.py",
            )
        )
        return cls(
            func_name=func_name,
            error_type=type(initial_exc).__name__,
            error_message=redact_sensitive_text(str(initial_exc)),
            traceback=redact_sensitive_text(tb_str),
            original_code=redact_sensitive_text(original_code),
            healed_code=redact_sensitive_text(healed_code),
            diff=redact_sensitive_text("".join(diff_lines)),
            attempts=attempts,
            provider=provider,
            model=model,
            timestamp=time.time(),
        )


class FunctionState:
    """Holds runtime state, active callable reference, concurrency locks, and telemetry."""

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
        self.last_proposed_report: Optional[HealReport] = None
        self.last_proposed_time: float = 0.0
        self.sync_lock = threading.Lock()
        self._async_lock: Optional[asyncio.Lock] = None

    @property
    def async_lock(self) -> asyncio.Lock:
        """Lazily initialize asyncio.Lock on the event loop executing the coroutine."""
        if self._async_lock is None:
            self._async_lock = asyncio.Lock()
        return self._async_lock


def _dispatch_on_heal(
    callback: Callable,
    report: HealReport,
    patch_code: str,
) -> None:
    """Dispatch sync on_heal callback with backwards-compatibility support."""
    try:
        callback(report)
    except TypeError:
        callback(report.func_name, patch_code)


async def _adispatch_on_heal(
    callback: Callable,
    report: HealReport,
    patch_code: str,
) -> None:
    """Dispatch async or sync on_heal callback with backwards-compatibility support."""
    if inspect.iscoroutinefunction(callback):
        await callback(report)
    else:
        _dispatch_on_heal(callback, report, patch_code)


def heal(
    schema: Optional[Type] = None,
    validate: Optional[Callable[[Any], bool]] = None,
    mode: str = "auto",
    propose_cooldown: float = 300.0,
    idempotent: bool = True,
    dry_run: bool = True,
    dry_run_timeout: float = 5.0,
    signature_only: bool = False,
    include_args: bool = True,
    max_retries: int = 3,
    provider: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    base_url: Optional[str] = None,
    timeout: float = 30.0,
    cache_dir: Optional[str] = ".kintsugi_cache",
    chain: Optional[List[Union[dict, LLMProvider]]] = None,
    on_heal: Optional[Callable[[Any], Any]] = None,
) -> Callable[[Callable[P, R]], Callable[P, R]]:
    """Decorator that empowers Python functions with autonomous self-healing capabilities."""

    def decorator(func: Callable[P, R]) -> Callable[P, R]:
        state = FunctionState(func, schema)
        cache = PatchCache(cache_dir)
        is_coroutine = inspect.iscoroutinefunction(func)

        # 1. Cold-start check: Rehydrate from disk cache if a patch already exists and mode == 'auto'
        if mode == "auto":
            cached_patch = cache.load_patch(state.func_name, state.fingerprint)
            if cached_patch:
                try:
                    fn_globals = getattr(func, "__globals__", {})
                    rehydrated_fn = compile_and_extract_function(
                        cached_patch, state.func_name, fn_globals
                    )
                    state.active_func = rehydrated_fn
                    state.is_healed = True
                    state.last_patch_code = cached_patch
                    logger.info("[Kintsugi] Rehydrated '%s' from disk cache.", state.func_name)
                except Exception as e:
                    logger.warning("[Kintsugi] Failed to rehydrate '%s' from cache: %s", state.func_name, e)
                    state.active_func = func

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
            async def async_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                initial_exc = None
                try:
                    result = await state.active_func(*args, **kwargs)
                    return validate_contract(result, schema, predicate=validate)
                except Exception as exc:
                    initial_exc = exc

                # Double-Checked Locking: Acquire async lock to prevent Thundering Herd
                async with state.async_lock:
                    if state.is_healed and mode == "auto":
                        try:
                            result = await state.active_func(*args, **kwargs)
                            return validate_contract(result, schema, predicate=validate)
                        except Exception as retry_exc:
                            initial_exc = retry_exc

                    # Cooldown deduplication in propose mode to prevent burning LLM calls
                    if mode == "propose" and state.last_proposed_report is not None:
                        elapsed = time.time() - state.last_proposed_time
                        if elapsed < propose_cooldown:
                            logger.debug(
                                "[Kintsugi] Returning cached proposal for '%s' (cooldown active: %.1fs remaining).",
                                state.func_name,
                                propose_cooldown - elapsed,
                            )
                            raise ProposedPatchError(
                                f"Patch proposed for '{state.func_name}' but not applied (mode='propose').",
                                report=state.last_proposed_report,
                            )

                    logger.warning(
                        "[Kintsugi] Error in '%s': %s. Initiating repair cycle (mode='%s')...",
                        state.func_name,
                        initial_exc,
                        mode,
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
                            signature_only=signature_only,
                            include_args=include_args,
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

                            # 3. Dry-run test with failing inputs if idempotent
                            if dry_run and idempotent:
                                raw_result = await asyncio.wait_for(
                                    candidate_fn(*args, **kwargs),
                                    timeout=dry_run_timeout,
                                )
                                validated_result = validate_contract(
                                    raw_result, schema, predicate=validate
                                )
                            else:
                                validated_result = None

                            report = HealReport.create(
                                func_name=state.func_name,
                                initial_exc=initial_exc,
                                tb_str=tb_str,
                                original_code=state.source_code,
                                healed_code=patch_code,
                                attempts=attempt,
                                provider=active_provider.__class__.__name__,
                                model=active_provider.model,
                            )

                            if on_heal:
                                await _adispatch_on_heal(on_heal, report, patch_code)

                            # If mode == 'propose', record proposal for cooldown deduplication and do not hot-swap
                            if mode == "propose":
                                state.last_proposed_report = report
                                state.last_proposed_time = time.time()
                                logger.info(
                                    "[Kintsugi] Validated patch proposal for '%s'. Halting execution as mode='propose'.",
                                    state.func_name,
                                )
                                raise ProposedPatchError(
                                    f"Patch proposed for '{state.func_name}' but not applied (mode='propose').",
                                    report=report,
                                )

                            # 4. Mode == 'auto': Hot-swap in memory!
                            state.active_func = candidate_fn
                            state.is_healed = True
                            state.heal_count += 1
                            state.last_patch_code = patch_code

                            # 5. Save to disk cache
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

                            if validated_result is not None:
                                return validated_result
                            return await candidate_fn(*args, **kwargs)

                        except ProposedPatchError:
                            raise
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

            async_wrapper.__kintsugi_state__ = state
            return async_wrapper

        else:
            @wraps(func)
            def sync_wrapper(*args: P.args, **kwargs: P.kwargs) -> R:
                initial_exc = None
                try:
                    result = state.active_func(*args, **kwargs)
                    return validate_contract(result, schema, predicate=validate)
                except Exception as exc:
                    initial_exc = exc

                # Double-Checked Locking: Acquire threading lock to prevent race conditions
                with state.sync_lock:
                    if state.is_healed and mode == "auto":
                        try:
                            result = state.active_func(*args, **kwargs)
                            return validate_contract(result, schema, predicate=validate)
                        except Exception as retry_exc:
                            initial_exc = retry_exc

                    # Cooldown deduplication in propose mode to prevent burning LLM calls
                    if mode == "propose" and state.last_proposed_report is not None:
                        elapsed = time.time() - state.last_proposed_time
                        if elapsed < propose_cooldown:
                            logger.debug(
                                "[Kintsugi] Returning cached proposal for '%s' (cooldown active: %.1fs remaining).",
                                state.func_name,
                                propose_cooldown - elapsed,
                            )
                            raise ProposedPatchError(
                                f"Patch proposed for '{state.func_name}' but not applied (mode='propose').",
                                report=state.last_proposed_report,
                            )

                    logger.warning(
                        "[Kintsugi] Error in '%s': %s. Initiating repair cycle (mode='%s')...",
                        state.func_name,
                        initial_exc,
                        mode,
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
                            signature_only=signature_only,
                            include_args=include_args,
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

                            # 3. Dry-run test with failing inputs if idempotent
                            if dry_run and idempotent:
                                raw_result = execute_with_timeout(
                                    candidate_fn, args, kwargs, timeout_sec=dry_run_timeout
                                )
                                validated_result = validate_contract(
                                    raw_result, schema, predicate=validate
                                )
                            else:
                                validated_result = None

                            report = HealReport.create(
                                func_name=state.func_name,
                                initial_exc=initial_exc,
                                tb_str=tb_str,
                                original_code=state.source_code,
                                healed_code=patch_code,
                                attempts=attempt,
                                provider=active_provider.__class__.__name__,
                                model=active_provider.model,
                            )

                            if on_heal:
                                _dispatch_on_heal(on_heal, report, patch_code)

                            # If mode == 'propose', record proposal for cooldown deduplication and do not hot-swap
                            if mode == "propose":
                                state.last_proposed_report = report
                                state.last_proposed_time = time.time()
                                logger.info(
                                    "[Kintsugi] Validated patch proposal for '%s'. Halting execution as mode='propose'.",
                                    state.func_name,
                                )
                                raise ProposedPatchError(
                                    f"Patch proposed for '{state.func_name}' but not applied (mode='propose').",
                                    report=report,
                                )

                            # 4. Mode == 'auto': Hot-swap in memory!
                            state.active_func = candidate_fn
                            state.is_healed = True
                            state.heal_count += 1
                            state.last_patch_code = patch_code

                            # 5. Save to disk cache
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

                            if validated_result is not None:
                                return validated_result
                            return candidate_fn(*args, **kwargs)

                        except ProposedPatchError:
                            raise
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

            sync_wrapper.__kintsugi_state__ = state
            return sync_wrapper

    return decorator
