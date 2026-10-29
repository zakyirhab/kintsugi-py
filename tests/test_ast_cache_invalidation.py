"""
AST-Aware Cache Invalidation & Pruning Tests for KintsugiPy.
"""

from pathlib import Path
import shutil
import pytest
from kintsugi.cache import PatchCache, compute_fingerprint

TEST_CACHE_DIR = ".test_ast_cache"


@pytest.fixture(autouse=True)
def cleanup():
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)


def test_comments_do_not_invalidate_cache():
    code_v1 = """
def calculate(a: int, b: int) -> int:
    return a + b
"""

    code_v2 = """
# Adding detailed comments
# TODO: review tomorrow
def calculate(a: int, b: int) -> int:
    # Inline explanation
    return a + b
"""

    fp1 = compute_fingerprint("calculate", code_v1)
    fp2 = compute_fingerprint("calculate", code_v2)

    # Identical AST structure -> identical fingerprint!
    assert fp1 == fp2


def test_logic_changes_cleanly_invalidate_cache():
    code_v1 = """
def calculate(a: int, b: int) -> int:
    return a + b
"""

    code_v2 = """
def calculate(a: int, b: int) -> int:
    return a * b
"""

    fp1 = compute_fingerprint("calculate", code_v1)
    fp2 = compute_fingerprint("calculate", code_v2)

    # Different logic -> different fingerprint!
    assert fp1 != fp2


def test_stale_cache_pruning():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "fetch_data"

    fp_old = "old1111111111111"
    fp_new = "new2222222222222"

    # Save old version
    cache.save_patch(func_name, fp_old, "def fetch_data(): return 1")
    assert (Path(TEST_CACHE_DIR) / f"{func_name}_{fp_old}.py").exists()

    # Save new version with different fingerprint
    cache.save_patch(func_name, fp_new, "def fetch_data(): return 2")

    # Old patch must be pruned automatically!
    assert not (Path(TEST_CACHE_DIR) / f"{func_name}_{fp_old}.py").exists()
    # New patch exists!
    assert (Path(TEST_CACHE_DIR) / f"{func_name}_{fp_new}.py").exists()
