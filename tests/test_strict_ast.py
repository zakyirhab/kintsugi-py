import pytest
from kintsugi.sandbox import (
    verify_code_safety,
    execute_with_timeout,
    SecurityViolationError,
)


def test_reject_dunder_subclasses_access():
    code = """
def malicious(x: str):
    cl = x.__class__.__bases__[0].__subclasses__()
    return cl
"""
    with pytest.raises(SecurityViolationError, match="Forbidden access to sensitive dunder attribute"):
        verify_code_safety(code, "malicious")


def test_reject_getattr_call():
    code = """
def sneaky_call(target, attr):
    fn = getattr(target, attr)
    return fn()
"""
    with pytest.raises(SecurityViolationError, match=r"Forbidden call to builtin: 'getattr\(\)'"):
        verify_code_safety(code, "sneaky_call")


def test_reject_globals_and_locals():
    code = """
def grab_env():
    return globals()
"""
    with pytest.raises(SecurityViolationError, match=r"Forbidden call to builtin: 'globals\(\)'"):
        verify_code_safety(code, "grab_env")


def test_timeout_catches_infinite_loop():
    def endless_loop():
        import time
        while True:
            time.sleep(0.01)

    with pytest.raises(TimeoutError, match="timed out after"):
        execute_with_timeout(endless_loop, (), {}, timeout_sec=0.2)
