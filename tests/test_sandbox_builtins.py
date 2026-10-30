import pytest
from kintsugi.sandbox import (
    verify_code_safety,
    compile_and_extract_function,
    SecurityViolationError,
    SAFE_BUILTINS,
)


def test_isinstance_type_check():
    # type must be a real type in SAFE_BUILTINS so isinstance(x, type) works
    assert isinstance(dict, SAFE_BUILTINS["type"])
    assert isinstance(int, SAFE_BUILTINS["type"])

    # Normal type check in safe code must pass
    safe_code = """
def check_type(val):
    return type(val) == int
"""
    tree = verify_code_safety(safe_code, "check_type")
    assert tree is not None

    fn = compile_and_extract_function(safe_code, "check_type")
    assert fn(42) is True
    assert fn("str") is False


def test_type_dynamic_class_creation_banned():
    exploit_code = """
def exploit():
    return type("Exploit", (), {})
"""
    with pytest.raises(SecurityViolationError, match="Dynamic class creation via type"):
        verify_code_safety(exploit_code, "exploit")


def test_type_starred_and_kwargs_banned():
    # type(*args) bypass attempt
    starred_code = """
def exploit(args):
    return type(*args)
"""
    with pytest.raises(SecurityViolationError, match="Dynamic class creation via type"):
        verify_code_safety(starred_code, "exploit")

    # type(**kwargs) bypass attempt
    kwargs_code = """
def exploit(kwargs):
    return type(**kwargs)
"""
    with pytest.raises(SecurityViolationError, match="Dynamic class creation via type"):
        verify_code_safety(kwargs_code, "exploit")


def test_patch_print_prefix(capsys):
    patch_code = """
def log_task():
    print("processing item 42")
    return "done"
"""
    fn = compile_and_extract_function(patch_code, "log_task")
    res = fn()
    assert res == "done"

    captured = capsys.readouterr()
    assert "[KINTSUGI-PATCH] processing item 42" in captured.out


def test_forbidden_builtins_rejected():
    for forbidden in ["eval", "exec", "open", "breakpoint", "exit", "quit", "help"]:
        code = f"def exploit():\n    return {forbidden}('x')\n"
        with pytest.raises(SecurityViolationError):
            verify_code_safety(code, "exploit")
