"""
Privacy & Secret Redaction Engine for KintsugiPy.
Ensures API keys, tokens, passwords, and sensitive PII never leak to LLMs.
"""

import re
from typing import Any

# Regex patterns for common sensitive tokens and PII
SECRET_PATTERNS = [
    # API Keys & Cloud Tokens
    (re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE), "[REDACTED_API_KEY]"),
    (re.compile(r"gsk_[a-zA-Z0-9_\-]{20,}", re.IGNORECASE), "[REDACTED_GROQ_KEY]"),
    (re.compile(r"AIzaSy[a-zA-Z0-9_\-]{33}"), "[REDACTED_GEMINI_KEY]"),
    (re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}", re.IGNORECASE), "[REDACTED_GITHUB_TOKEN]"),
    (re.compile(r"Bearer\s+[a-zA-Z0-9_\-\.]+", re.IGNORECASE), "Bearer [REDACTED_TOKEN]"),
    (re.compile(r"ey[a-zA-Z0-9_\-]{4,}\.ey[a-zA-Z0-9_\-]{4,}\.[a-zA-Z0-9_\-]+"), "[REDACTED_JWT]"),
    # Passwords and secrets in representations
    (
        re.compile(
            r"(['\"]?(?:password|passwd|secret|api_key|access_token|private_key)['\"]?\s*[:=]\s*)['\"][^'\"]+['\"]",
            re.IGNORECASE,
        ),
        r"\1'[REDACTED]'",
    ),
    # Credit Card numbers (Luhn candidate 16 digits)
    (re.compile(r"\b(?:\d{4}[ -]?){3}\d{4}\b"), "[REDACTED_CARD]"),
    # Email addresses
    (re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b"), "[REDACTED_EMAIL]"),
]


def redact_sensitive_text(text: str) -> str:
    """Scrub known API keys, tokens, passwords, and PII from raw string representation."""
    redacted = text
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def sanitize_runtime_value(
    val: Any,
    signature_only: bool = False,
    max_len: int = 3000,
) -> str:
    """Safely serialize an argument for LLM prompt transmission.
    
    If signature_only is True, only the structural shape and type is sent
    (e.g. `<str len=45>` or `<dict keys=['user', 'email']>`), preventing any raw data leakage.
    """
    if signature_only:
        val_type = type(val).__name__
        if isinstance(val, (str, bytes)):
            return f"<{val_type} len={len(val)}>"
        elif isinstance(val, dict):
            keys = list(val.keys())[:10]
            return f"<dict len={len(val)} keys={keys}>"
        elif isinstance(val, (list, tuple, set)):
            return f"<{val_type} len={len(val)}>"
        return f"<{val_type}>"

    # Full value with smart trim and secret redaction
    raw = repr(val)
    if len(raw) > max_len:
        half = max_len // 2
        trimmed = f"{raw[:half]}\n... [TRUNCATED {len(raw) - max_len} CHARS] ...\n{raw[-half:]}"
    else:
        trimmed = raw

    return redact_sensitive_text(trimmed)
