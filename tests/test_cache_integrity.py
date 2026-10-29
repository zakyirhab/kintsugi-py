from pathlib import Path
import shutil
import pytest
from kintsugi.cache import PatchCache, compute_patch_checksum

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


def test_fail_closed_when_metadata_missing():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "sample_fn"
    fp = "fp123456789"
    patch_code = "def sample_fn(): return 1\n"

    cache.save_patch(func_name, fp, patch_code)
    # Deliberately remove .json metadata file
    meta_file = Path(TEST_CACHE_DIR) / f"{func_name}_{fp}.json"
    meta_file.unlink()

    # Fail-closed policy: without metadata HMAC, patch is rejected!
    assert cache.load_patch(func_name, fp) is None


def test_transposed_patch_between_functions_rejected():
    cache = PatchCache(TEST_CACHE_DIR)
    func_a = "func_a"
    func_b = "func_b"
    fp = "common_fp"
    patch_a = "def func_a(): return 1\n"

    # Save patch for func_a
    cache.save_patch(func_a, fp, patch_a)

    # Copy files of func_a to func_b
    patch_a_file = Path(TEST_CACHE_DIR) / f"{func_a}_{fp}.py"
    meta_a_file = Path(TEST_CACHE_DIR) / f"{func_a}_{fp}.json"
    patch_b_file = Path(TEST_CACHE_DIR) / f"{func_b}_{fp}.py"
    meta_b_file = Path(TEST_CACHE_DIR) / f"{func_b}_{fp}.json"

    patch_b_file.write_text(patch_a_file.read_text())
    meta_b_file.write_text(meta_a_file.read_text())

    # load_patch for func_b must reject because HMAC binds func_name!
    assert cache.load_patch(func_b, fp) is None


def test_insecure_cached_patch_rejected_by_ast_on_load():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "unsafe_func"
    fp = "xyz987654321"

    patch_file = Path(TEST_CACHE_DIR) / f"{func_name}_{fp}.py"
    patch_file.write_text("def unsafe_func():\n    import os\n    return 0\n", encoding="utf-8")

    assert cache.load_patch(func_name, fp) is None
