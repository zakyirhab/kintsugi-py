from dataclasses import dataclass
import pytest
from pydantic import BaseModel
from kintsugi.sandbox import (
    verify_code_safety,
    compile_and_extract_function,
    is_allowed_global_object,
    SecurityViolationError,
)


def test_package_local_and_pydantic_allowed():
    # 1. Pydantic model
    class UserSchema(BaseModel):
        id: int
        name: str

    # 2. Dataclass model
    @dataclass
    class ItemData:
        sku: str
        qty: int

    # 3. Local package helper
    def local_helper(x: int) -> int:
        return x * 2

    local_helper.__module__ = "myapp.utils"

    globals_dict = {
        "UserSchema": UserSchema,
        "ItemData": ItemData,
        "local_helper": local_helper,
        "__name__": "myapp.service",
    }

    # Verify is_allowed_global_object
    assert is_allowed_global_object(UserSchema, target_module="myapp.service") is True
    assert is_allowed_global_object(ItemData, target_module="myapp.service") is True
    assert is_allowed_global_object(local_helper, target_module="myapp.service") is True

    patch_code = """
def process(x: int):
    u = UserSchema(id=x, name="alice")
    it = ItemData(sku="SKU1", qty=local_helper(x))
    return u.id + it.qty
"""
    fn = compile_and_extract_function(
        patch_code, "process", closure_globals=globals_dict, target_module="myapp.service"
    )
    assert fn(5) == 5 + 10


def test_myapp_evil_rejected():
    # Helper from myapp_evil must NOT pass when pkg is myapp
    def evil_helper():
        return "pwned"

    evil_helper.__module__ = "myapp_evil.helpers"

    assert is_allowed_global_object(evil_helper, target_module="myapp.service") is False

    globals_dict = {
        "evil_helper": evil_helper,
        "__name__": "myapp.service",
    }

    patch_code = """
def run_task():
    return evil_helper()
"""
    # evil_helper will NOT be copied into namespace, leading to NameError
    fn = compile_and_extract_function(
        patch_code, "run_task", closure_globals=globals_dict, target_module="myapp.service"
    )
    with pytest.raises(NameError, match="name 'evil_helper' is not defined"):
        fn()


def test_block_global_and_nonlocal_statements():
    global_code = """
def leak():
    global _secret_cache
    _secret_cache = 42
"""
    with pytest.raises(SecurityViolationError, match="Forbidden statement: 'global'"):
        verify_code_safety(global_code, "leak")

    nonlocal_code = """
def outer():
    x = 1
    def leak():
        nonlocal x
        x = 2
"""
    with pytest.raises(SecurityViolationError, match="Forbidden statement: 'nonlocal'"):
        verify_code_safety(nonlocal_code, "outer")


def test_os_system_from_globals_blocked():
    import os

    # Suppose user's file had 'from os import system' or 'import os'
    globals_dict = {
        "system": os.system,
        "os": os,
        "__name__": "myapp.controller",
    }

    assert is_allowed_global_object(os.system, target_module="myapp.controller") is False
    assert is_allowed_global_object(os, target_module="myapp.controller") is False

    patch_code = """
def trigger():
    return system("echo hacked")
"""
    fn = compile_and_extract_function(
        patch_code, "trigger", closure_globals=globals_dict, target_module="myapp.controller"
    )
    with pytest.raises(NameError, match="name 'system' is not defined"):
        fn()
