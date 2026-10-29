import pytest
from kintsugi.sandbox import verify_code_safety, SecurityViolationError


def test_safe_function_passes():
    code = """
def extract_price(text: str) -> int:
    import re
    cleaned = re.sub(r'[^0-9]', '', text)
    return int(cleaned) if cleaned else 0
"""
    tree = verify_code_safety(code, "extract_price")
    assert tree is not None


def test_missing_function_name_rejected():
    code = """
def wrong_name(text: str):
    return text
"""
    with pytest.raises(SecurityViolationError, match="does not contain the required function"):
        verify_code_safety(code, "extract_price")


def test_syntax_error_rejected():
    code = """
def extract_price(text: str)
    return 123
"""
    with pytest.raises(SecurityViolationError, match="Syntax error"):
        verify_code_safety(code, "extract_price")


def test_forbidden_import_os_rejected():
    code = """
def extract_price(text: str):
    import os
    os.system("echo hacked")
    return 0
"""
    with pytest.raises(SecurityViolationError, match="Forbidden module import: 'os'"):
        verify_code_safety(code, "extract_price")


def test_forbidden_import_from_subprocess_rejected():
    code = """
def extract_price(text: str):
    from subprocess import Popen
    return 0
"""
    with pytest.raises(SecurityViolationError, match="Forbidden module import from: 'subprocess'"):
        verify_code_safety(code, "extract_price")


def test_forbidden_eval_call_rejected():
    code = """
def extract_price(text: str):
    return eval(text)
"""
    with pytest.raises(SecurityViolationError, match=r"Forbidden call to builtin: 'eval\(\)'"):
        verify_code_safety(code, "extract_price")


def test_forbidden_open_call_rejected():
    code = """
def extract_price(text: str):
    with open("secret.txt", "w") as f:
        f.write("test")
    return 0
"""
    with pytest.raises(SecurityViolationError, match=r"Forbidden call to builtin: 'open\(\)'"):
        verify_code_safety(code, "extract_price")
