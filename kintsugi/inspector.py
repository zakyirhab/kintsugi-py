"""
Crime Scene Inspector for KintsugiPy.
Extracts source code, traceback, and serializes arguments with privacy redaction.
"""

import inspect
import logging
import textwrap
import traceback
from typing import Any, Callable, Dict, Optional, Tuple, Type

from kintsugi.privacy import (
    map_and_replace_secrets,
    redact_sensitive_text,
    sanitize_runtime_value,
)

logger = logging.getLogger("kintsugi.inspector")


def smart_trim(value: Any, max_len: int = 3000) -> str:
    """Safely convert value to string, sanitize secrets, and trim if exceeding max_len."""
    return sanitize_runtime_value(value, signature_only=False, max_len=max_len)


def extract_function_source(func: Callable) -> Optional[str]:
    """Retrieve clean, unindented source code of a callable, excluding decorator lines.
    
    Returns None if inspect.getsource fails (e.g. lambda, REPL, compiled .pyc without source).
    """
    if getattr(func, "__name__", "") == "<lambda>":
        return None

    try:
        raw_source = inspect.getsource(func)
        dedented = textwrap.dedent(raw_source)
        # Strip leading decorator lines so fingerprint and LLM prompt only contain the function body
        lines = dedented.splitlines(keepends=True)
        start_idx = -1
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                start_idx = i
                break
        if start_idx == -1:
            return None
        return "".join(lines[start_idx:])
    except Exception as e:
        logger.debug("[Kintsugi] inspect.getsource failed for %s: %s", getattr(func, "__name__", str(func)), e)
        return None


def get_schema_summary(schema: Optional[Type]) -> str:
    """Extract a human-readable representation of a Pydantic model or return type."""
    if schema is None:
        return "No explicit schema enforced. Return the intended logical data structure."

    if hasattr(schema, "model_fields"):
        fields_desc = []
        for name, field in schema.model_fields.items():
            ann = getattr(field, "annotation", Any)
            fields_desc.append(f"  - {name}: {ann}")
        return f"Pydantic Model '{schema.__name__}':\n" + "\n".join(fields_desc)

    return f"Expected Type: {getattr(schema, '__name__', str(schema))}"


def build_repair_prompt(
    func: Callable,
    source_code: str,
    exc: Exception,
    tb_str: str,
    args: Tuple[Any, ...],
    kwargs: Dict[str, Any],
    schema: Optional[Type] = None,
    signature_only: bool = False,
    include_args: bool = True,
) -> Tuple[str, str, Dict[str, str]]:
    """Construct system prompt and user prompt for the LLM repair surgeon with privacy scrubbing."""
    system_prompt = (
        "You are Kintsugi, an autonomous Python code repair surgeon.\n"
        "A runtime error occurred in a Python function.\n"
        "Your task is to rewrite the function so that it handles the runtime data correctly and fulfills the required output contract.\n\n"
        "STRICT OPERATIONAL RULES:\n"
        "1. Output ONLY executable Python code inside a ```python ... ``` block.\n"
        "2. Keep the EXACT same function name and signature.\n"
        "3. Do NOT import destructive libraries (os, sys, subprocess, shutil, eval, exec, ctypes).\n"
        "4. The return value MUST match the target schema specification.\n"
        "5. No pleasantries, no conversational filler, no explanations."
    )

    clean_source, secret_map = map_and_replace_secrets(source_code)
    if secret_map:
        logger.warning(
            "[Kintsugi] Detected %d hardcoded secret(s) in '%s'. Reversibly masked for LLM repair. "
            "Consider moving secrets to environment variables.",
            len(secret_map),
            func.__name__,
        )

    if include_args:
        trimmed_args = [sanitize_runtime_value(a, signature_only=signature_only) for a in args]
        trimmed_kwargs = {
            k: sanitize_runtime_value(v, signature_only=signature_only) for k, v in kwargs.items()
        }
        args_section = f"args: {trimmed_args}\nkwargs: {trimmed_kwargs}"
    else:
        args_section = "[Input arguments omitted by privacy policy]"

    schema_info = get_schema_summary(schema)
    clean_exc_msg = redact_sensitive_text(str(exc))
    clean_tb = redact_sensitive_text(tb_str)

    user_prompt = f"""### BROKEN FUNCTION: `{func.__name__}`

```python
{clean_source}
```

### RUNTIME EXCEPTION:
Type: {type(exc).__name__}
Message: {clean_exc_msg}

### TRACEBACK:
{clean_tb}

### INPUT ARGUMENTS AT CRASH:
{args_section}

### REQUIRED OUTPUT CONTRACT:
{schema_info}

Please write the complete, corrected version of `{func.__name__}` that will successfully process this input and conform to the schema:
"""
    return system_prompt, user_prompt, secret_map
