import pytest
from kintsugi.privacy import redact_sensitive_text, sanitize_runtime_value
from kintsugi.inspector import build_repair_prompt


def test_redact_api_keys():
    raw = "My OpenAI key is sk-1234567890abcdef1234567890 and Groq is gsk_abcdef1234567890abcdef"
    clean = redact_sensitive_text(raw)
    assert "sk-1234567890abcdef1234567890" not in clean
    assert "[REDACTED_API_KEY]" in clean
    assert "gsk_abcdef1234567890abcdef" not in clean
    assert "[REDACTED_GROQ_KEY]" in clean


def test_redact_bearer_and_jwt():
    raw = "Authorization: Bearer my_secret_token_abc.123 and token eyJhbGciOi.eyJzdWIiOi.signature"
    clean = redact_sensitive_text(raw)
    assert "Bearer [REDACTED_TOKEN]" in clean
    assert "[REDACTED_JWT]" in clean


def test_redact_password_and_email():
    raw = "{'user': 'alice', 'password': 'super_secret_123', 'email': 'alice@company.org'}"
    clean = redact_sensitive_text(raw)
    assert "super_secret_123" not in clean
    assert "[REDACTED]" in clean
    assert "alice@company.org" not in clean
    assert "[REDACTED_EMAIL]" in clean


def test_signature_only_sanitization():
    secret_payload = {"user": "bob", "apiKey": "sk-secret1234567890abcdef", "roles": ["admin"]}
    sanitized = sanitize_runtime_value(secret_payload, signature_only=True)
    # Must only contain shape, no values
    assert "bob" not in sanitized
    assert "sk-secret" not in sanitized
    assert "<dict len=3 keys=['user', 'apiKey', 'roles']>" == sanitized

    string_val = "Super secret text payload"
    sanitized_str = sanitize_runtime_value(string_val, signature_only=True)
    assert sanitized_str == "<str len=25>"


def test_build_repair_prompt_privacy_options():
    def dummy_func(token: str, data: dict):
        pass

    sys_p, user_p, secret_map = build_repair_prompt(
        func=dummy_func,
        source_code="def dummy_func(token, data): pass",
        exc=ValueError("Invalid sk-secretkey1234567890abcdef"),
        tb_str="Traceback: line 1 in dummy_func",
        args=("sk-secretkey1234567890abcdef", {"email": "boss@corp.com"}),
        kwargs={},
        signature_only=True,
    )
    # The prompt must NOT leak the secret key or email
    assert "sk-secretkey1234567890abcdef" not in user_p
    assert "boss@corp.com" not in user_p
    assert "<str len=" in user_p
    assert "<dict len=" in user_p
