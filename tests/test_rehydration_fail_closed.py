from pathlib import Path
import shutil
import pytest
from kintsugi.cache import PatchCache

TEST_CACHE_DIR = ".test_rehydrate_cache"


@pytest.fixture(autouse=True)
def cleanup():
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)
    yield
    shutil.rmtree(TEST_CACHE_DIR, ignore_errors=True)


def test_rehydration_fail_closed_on_secret_migration():
    cache = PatchCache(TEST_CACHE_DIR)
    func_name = "api_client"
    fp = "fp987654321"

    raw_patch = """
def api_client(client, url):
    return client.post(url, headers={"Authorization": "__KINTSUGI_SECRET_0__"})
"""
    # Patch was saved with 1 placeholder
    cache.save_patch(
        func_name,
        fp,
        raw_patch,
        metadata={"placeholder_count": 1},
    )

    # 1. Matching source code: token is present as string literal
    matching_source = """
def api_client(client, url):
    key = "sk-1234567890abcdef1234567890"
    return client.post(url, headers={"Authorization": key})
"""
    rehydrated = cache.load_patch(func_name, fp, original_source=matching_source)
    assert rehydrated is not None
    assert "sk-1234567890abcdef1234567890" in rehydrated
    assert "__KINTSUGI_SECRET_0__" not in rehydrated

    # 2. User moved secret to env var! Current source code has NO string literal token:
    migrated_source = """
def api_client(client, url):
    import os
    key = os.environ.get("MY_API_KEY")
    return client.post(url, headers={"Authorization": key})
"""
    # load_patch must reject the patch and return None (fail-closed)
    failed_rehydration = cache.load_patch(func_name, fp, original_source=migrated_source)
    assert failed_rehydration is None
