"""
Crime Scene Inspector for KintsugiPy.
Extracts source code, traceback, and slices runtime arguments safely.
"""

import inspect
import textwrap
import traceback
from typing import Any, Callable, Dict, Optional, Tuple, Type


def smart_trim(value: Any, max_len: int = 3000) -> str:
    """Safely convert value to string and trim if exceeding max_len to protect LLM context."""
    s = repr(value)
    if len(s) > max_len:
        half = max_len // 2
        return f"{s[:half]}\n... [TRUNCATED {len(s) - max_len} CHARS] ...\n{s[-half:]}"
    return s


def extract_function_source(func: Callable) -> str:
    """Retrieve clean, unindented source code of a callable, excluding decorator lines."""
    try:
        raw_source = inspect.getsource(func)
        dedented = textwrap.dedent(raw_source)
        # Strip leading decorator lines so fingerprint and LLM prompt only contain the function body
        lines = dedented.splitlines(keepends=True)
        start_idx = 0
        for i, line in enumerate(lines):
            stripped = line.strip()
            if stripped.startswith("def ") or stripped.startswith("async def "):
                start_idx = i
                break
        return "".join(lines[start_idx:])
    except Exception as e:
        return f"# Could not inspect source for {func.__name__}: {str(e)}"


def get_schema_summary(schema: Optional[Type]) -> str:
    """Extract a human-readable representation of a Pydantic model or return type."""
    if schema is None:
        return "No explicit schema enforced. Return the intended logical data structure."

    # If it's a Pydantic v2 BaseModel
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
) -> Tuple[str, str]:
    """Construct system prompt and user prompt for the LLM repair surgeon."""
    system_prompt = (
        "You are Kintsugi, an autonomous Python code repair surgeon.\n"
        "A runtime error occurred in a Python function.\n"
        "Your task is to rewrite the function so that it handles the runtime data correctly and fulfills the required output contract.\n\n"
        "STRICT OPERATIONAL RULES:\n"
        "1. Output ONLY executable Python code inside a ```python ... ``` block.\n"
        "2. Keep the EXACT same function name and signature.\n"
        "3. Do NOT import destructive libraries (os, sys, subprocess, shutil, eval, exec).\n"
        "4. The return value MUST match the target schema specification.\n"
        "5. No pleasantries, no conversational filler, no explanations."
    )

    trimmed_args = [smart_trim(a) for a in args]
    trimmed_kwargs = {k: smart_trim(v) for k, v in kwargs.items()}
    schema_info = get_schema_summary(schema)

    user_prompt = f"""### BROKEN FUNCTION: `{func.__name__}`

```python
{source_code}
```

### RUNTIME EXCEPTION:
Type: {type(exc).__name__}
Message: {str(exc)}

### TRACEBACK:
{tb_str}

### INPUT ARGUMENTS AT CRASH:
args: {trimmed_args}
kwargs: {trimmed_kwargs}

### REQUIRED OUTPUT CONTRACT:
{schema_info}

Please write the complete, corrected version of `{func.__name__}` that will successfully process this input and conform to the schema:
"""
    return system_prompt, user_prompt
