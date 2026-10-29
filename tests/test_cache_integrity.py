from pathlib import Path
import shutil
import pytest
from kintsugi.cache import PatchCache, compute_fingerprint

TEST_CACHE_DIR = ".test_integrity_cache"


@pytest.fixture(autouse=True)
def cleanup():
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)


def test_cache_creates_gitignore_automatically():
    cache = PatchCache(TEST_CACHE_DIR)
    gi = Path(TEST_CACHE_DIR) / ".gitignore"
    assert gi.exists()
    assert "*\n" in gi.read_text()


def test_tampered_patch_is_rejected_by_hmac():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "test_func"
    fp = "abc123456789"
    original_patch = "def test_func():\n    return 42\n"

    # Save legitimate patch
    cache.save_patch(func_name, fp, original_patch, metadata={"test": True})

    # Legitimate load passes
    assert cache.load_patch(func_name, fp) == original_patch

    # Now an external process maliciously tampers with the .py file
    patch_file = Path(TEST_CACHE_DIR) / f"{func_name}_{fp}.py"
    patch_file.write_text("def test_func():\n    return 9999\n", encoding="utf-8")

    # load_patch must detect HMAC mismatch and reject the tampered patch
    assert cache.load_patch(func_name, fp) is None


def test_insecure_cached_patch_rejected_by_ast_on_load():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "unsafe_func"
    fp = "xyz987654321"

    # Suppose a file was written to disk with dangerous import
    patch_file = Path(TEST_CACHE_DIR) / f"{func_name}_{fp}.py"
    patch_file.write_text("def unsafe_func():\n    import os\n    return 0\n", encoding="utf-8")

    # load_patch must reject it due to AST guardrail
    assert cache.load_patch(func_name, fp) is None
