"""
Privacy & Secret Redaction Engine for KintsugiPy.
Ensures API keys, tokens, passwords, and sensitive PII never leak to LLMs.
"""

import re
from typing import Any, Dict, Tuple

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

import ast
import re
from typing import Any, Dict, List, Optional, Set, Tuple

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

# Patterns for hardcoded secrets that must be reversibly mapped in source code
REVERSIBLE_SECRET_PATTERNS = [
    re.compile(r"sk-[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"gsk_[a-zA-Z0-9_\-]{20,}", re.IGNORECASE),
    re.compile(r"AIzaSy[a-zA-Z0-9_\-]{33}"),
    re.compile(r"gh[pousr]_[a-zA-Z0-9]{36,}", re.IGNORECASE),
    re.compile(r"Bearer\s+([a-zA-Z0-9_\-\.]+)", re.IGNORECASE),
    re.compile(r"ey[a-zA-Z0-9_\-]{4,}\.ey[a-zA-Z0-9_\-]{4,}\.[a-zA-Z0-9_\-]+"),
]

HTTP_VERB_METHODS: Set[str] = {
    "get",
    "post",
    "put",
    "patch",
    "delete",
    "head",
    "options",
}


def redact_sensitive_text(text: str) -> str:
    """Scrub known API keys, tokens, passwords, and PII from raw string representation."""
    redacted = text
    for pattern, replacement in SECRET_PATTERNS:
        redacted = pattern.sub(replacement, redacted)
    return redacted


def map_and_replace_secrets(text: str) -> Tuple[str, Dict[str, str]]:
    """Scan source code for hardcoded secrets, replacing each with a reversible placeholder.
    
    Returns:
        (sanitized_text, mapping_of_placeholder_to_original_secret)
    """
    secret_map: Dict[str, str] = {}
    counter = 0

    def replacer(match: re.Match) -> str:
        nonlocal counter
        matched_str = match.group(0)
        for placeholder, secret in secret_map.items():
            if secret == matched_str:
                return placeholder

        placeholder = f"__KINTSUGI_SECRET_{counter}__"
        counter += 1
        secret_map[placeholder] = matched_str
        return placeholder

    sanitized = text
    for pattern in REVERSIBLE_SECRET_PATTERNS:
        sanitized = pattern.sub(replacer, sanitized)

    return sanitized, secret_map


def _node_contains_placeholder(node: ast.AST, placeholders: Set[str]) -> bool:
    """Check if an AST node directly or indirectly contains a placeholder string."""
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            if any(ph in child.value for ph in placeholders):
                return True
        elif isinstance(child, ast.Name) and child.id in placeholders:
            return True
    return False


def validate_patch_placeholder_safety(
    patch_code: str,
    original_source: str,
    secret_map: Dict[str, str],
) -> None:
    """Perform scope-aware AST validation on secret placeholder usage in LLM-generated patch.
    
    Rules enforced:
    1. Direct return of placeholder (as value or dictionary) is forbidden.
    2. Binary operation string concatenation with placeholder is forbidden.
    3. Method calls carrying placeholders must be authorized HTTP verbs (HTTP_VERB_METHODS).
       Methods like 'request' and 'send' are strictly rejected.
    4. Anti-exfiltration URL binding: Placeholder cannot be in URL position, and patch cannot
       introduce new string literal URLs with http:// or https:// not present in original source.
    """
    if not secret_map:
        return

    placeholders = set(secret_map.keys())

    try:
        patch_tree = ast.parse(patch_code)
    except Exception as e:
        raise ValueError(f"Syntax error in patch during placeholder validation: {e}") from e

    try:
        orig_tree = ast.parse(original_source)
    except Exception:
        orig_tree = None

    # Collect known string constants from original source
    orig_strings: Set[str] = set()
    if orig_tree:
        for node in ast.walk(orig_tree):
            if isinstance(node, ast.Constant) and isinstance(node.value, str):
                orig_strings.add(node.value)

    # Check for direct returns
    for node in ast.walk(patch_tree):
        if isinstance(node, ast.Return) and node.value is not None:
            if not isinstance(node.value, (ast.Call, ast.BinOp)):
                if _node_contains_placeholder(node.value, placeholders):
                    raise ValueError(
                        "Security violation: Secret placeholder returned directly from function."
                    )

        # Check for binary operation string concatenation (e.g. placeholder + '@attacker.com')
        if isinstance(node, ast.BinOp):
            if _node_contains_placeholder(node.left, placeholders) or _node_contains_placeholder(node.right, placeholders):
                raise ValueError(
                    "Security violation: Binary operation string concatenation with secret placeholder is forbidden."
                )

        # Check for dictionary keys (must not be placeholder)
        if isinstance(node, ast.Dict):
            for k in node.keys:
                if k is not None and _node_contains_placeholder(k, placeholders):
                    raise ValueError(
                        "Security violation: Secret placeholder used as dictionary key."
                    )

        # Check method calls
        if isinstance(node, ast.Call):
            if _node_contains_placeholder(node, placeholders):
                # Inspect target method
                method_name: Optional[str] = None
                if isinstance(node.func, ast.Attribute):
                    method_name = node.func.attr
                elif isinstance(node.func, ast.Name):
                    method_name = node.func.id

                if method_name not in HTTP_VERB_METHODS:
                    raise ValueError(
                        f"Security violation: Method '{method_name}' is not an authorized safe sink for secret placeholders."
                    )

                # Check URL position: placeholder forbidden in args[0] or kw.arg == 'url'
                if node.args and _node_contains_placeholder(node.args[0], placeholders):
                    raise ValueError(
                        "Security violation: Secret placeholder placed in URL destination position."
                    )
                for kw in node.keywords:
                    if kw.arg == "url" and _node_contains_placeholder(kw.value, placeholders):
                        raise ValueError(
                            "Security violation: Secret placeholder placed in 'url' destination argument."
                        )

                # Anti-exfiltration destination check
                url_node = node.args[0] if node.args else next((kw.value for kw in node.keywords if kw.arg == "url"), None)
                if isinstance(url_node, ast.Constant) and isinstance(url_node.value, str):
                    dest = url_node.value
                    if (dest.startswith("http://") or dest.startswith("https://")) and dest not in orig_strings:
                        raise ValueError(
                            f"Security violation: Untrusted destination URL '{dest}' introduced in patch."
                        )


def restore_mapped_secrets(
    patch_code: str,
    secret_map: Dict[str, str],
    original_source: Optional[str] = None,
) -> str:
    """Restore reversible placeholders in LLM generated patch back to original secret strings.
    
    Validates AST safe sinks before restoring and rejects unmapped '[REDACTED]' strings.
    """
    if original_source:
        validate_patch_placeholder_safety(patch_code, original_source, secret_map)

    restored = patch_code
    for placeholder, original in secret_map.items():
        restored = restored.replace(placeholder, original)

    if "[REDACTED" in restored:
        raise ValueError(
            "Generated patch contains unmapped '[REDACTED]' placeholder, which would break runtime execution. "
            "Ensure secrets are provided via environment variables rather than hardcoded in source."
        )

    return restored


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
