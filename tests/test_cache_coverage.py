import os
import json
import secrets
from pathlib import Path
import pytest
from unittest.mock import patch, MagicMock

import kintsugi.cache as cache_module
from kintsugi.cache import (
    reset_cache_secret,
    is_persistent_secret,
    get_cache_secret,
    compute_fingerprint,
    compute_patch_checksum,
    PatchCache,
)


@pytest.fixture(autouse=True)
def clean_secret_state():
    cache_module.reset_cache_secret()
    old_env = os.environ.get("KINTSUGI_CACHE_SECRET")
    yield
    cache_module.reset_cache_secret()
    if old_env is not None:
        os.environ["KINTSUGI_CACHE_SECRET"] = old_env
    else:
        os.environ.pop("KINTSUGI_CACHE_SECRET", None)


def test_is_persistent_secret_initial_call():
    reset_cache_secret()
    # Calling is_persistent_secret without prior get_cache_secret
    val = is_persistent_secret()
    assert isinstance(val, bool)


def test_env_cache_secret(monkeypatch):
    reset_cache_secret()
    custom_secret = "custom_secret_key_1234567890"
    monkeypatch.setenv("KINTSUGI_CACHE_SECRET", custom_secret)
    sec = get_cache_secret()
    assert sec == custom_secret
    assert is_persistent_secret() is True


def test_posix_permission_checks(tmp_path, monkeypatch):
    reset_cache_secret()
    fake_home = tmp_path / "home"
    fake_home.mkdir()
    secret_file = fake_home / ".kintsugi_machine_secret"
    secret_file.write_text("a" * 32, encoding="utf-8")

    monkeypatch.setattr(Path, "home", lambda: fake_home)

    # 1. Mismatched UID (simulate posix check branch without changing os.name globally)
    original_getuid = getattr(os, "getuid", None)
    monkeypatch.setattr(cache_module.os, "name", "posix")
    monkeypatch.setattr(cache_module.os, "getuid", lambda: 1000, raising=False)

    mock_stat = MagicMock(st_uid=2000, st_mode=0o600)
    with patch.object(Path, "stat", return_value=mock_stat):
        sec = get_cache_secret()
        # Mismatch UID triggers ephemeral fallback
        assert is_persistent_secret() is False
        assert len(sec) == 64

    reset_cache_secret()
    # 2. Permissive mode (e.g. 0666)
    mock_stat = MagicMock(st_uid=1000, st_mode=0o666)
    with patch.object(Path, "stat", return_value=mock_stat):
        sec = get_cache_secret()
        assert is_persistent_secret() is False

    reset_cache_secret()
    # 3. Clean posix match
    mock_stat = MagicMock(st_uid=1000, st_mode=0o600)
    with patch.object(Path, "stat", return_value=mock_stat):
        sec = get_cache_secret()
        assert is_persistent_secret() is True
        assert sec == "a" * 32


def test_machine_secret_file_creation(tmp_path, monkeypatch):
    reset_cache_secret()
    fake_home = tmp_path / "new_home"
    fake_home.mkdir()
    monkeypatch.setattr(Path, "home", lambda: fake_home)

    sec = get_cache_secret()
    assert is_persistent_secret() is True
    assert len(sec) >= 32
    assert (fake_home / ".kintsugi_machine_secret").exists()


def test_compute_fingerprint_syntax_fallback():
    # Invalid Python syntax must fall back to string hash without raising
    invalid_py = "def def def :::"
    fp = compute_fingerprint("bad_syntax", invalid_py)
    assert isinstance(fp, str)
    assert len(fp) == 16


def test_cache_disabled_when_secret_not_persistent(monkeypatch):
    reset_cache_secret()
    # Force fallback to ephemeral secret
    monkeypatch.setattr(cache_module, "is_persistent_secret", lambda: False)
    cache = PatchCache(".tmp_cache")
    assert cache.is_enabled() is False
    assert cache.save_patch("fn", "fp", "code") is False
    assert cache.load_patch("fn", "fp") is None
    assert cache.prune_stale_patches("fn", "fp") == 0


def test_missing_checksum_in_metadata(tmp_path):
    cache = PatchCache(str(tmp_path))
    patch_file = tmp_path / "myfunc_fp1.py"
    meta_file = tmp_path / "myfunc_fp1.json"

    patch_file.write_text("def myfunc(): pass\n", encoding="utf-8")
    # Metadata missing checksum key
    meta_file.write_text(json.dumps({"func_name": "myfunc"}), encoding="utf-8")

    res = cache.load_patch("myfunc", "fp1")
    assert res is None


def test_rehydration_missing_original_source(tmp_path):
    cache = PatchCache(str(tmp_path))
    code = 'def myfunc(): return "__KINTSUGI_SECRET_0__"\n'
    cache.save_patch("myfunc", "fp1", code, metadata={"placeholder_count": 1})

    # load without original_source
    res = cache.load_patch("myfunc", "fp1", original_source=None)
    assert res is None


def test_rehydration_restoration_error(tmp_path):
    cache = PatchCache(str(tmp_path))
    code = 'def myfunc(): return "__KINTSUGI_SECRET_0__"\n'
    cache.save_patch("myfunc", "fp1", code, metadata={"placeholder_count": 1})

    # Source has a secret, but placeholder returned directly raises ValueError in restore_mapped_secrets
    source_with_secret = 'def myfunc(): key = "sk-1234567890abcdef1234567890"\n'
    res = cache.load_patch("myfunc", "fp1", original_source=source_with_secret)
    assert res is None


def test_save_patch_exception_handling(tmp_path):
    cache = PatchCache(str(tmp_path))
    with patch.object(Path, "write_text", side_effect=OSError("Disk full")):
        ok = cache.save_patch("myfunc", "fp1", "def myfunc(): pass")
        assert ok is False


def test_prune_stale_patches_unlink_error(tmp_path):
    cache = PatchCache(str(tmp_path))
    old_file = tmp_path / "myfunc_oldfp.py"
    old_file.write_text("def myfunc(): pass", encoding="utf-8")

    with patch.object(Path, "unlink", side_effect=OSError("Locked")):
        pruned = cache.prune_stale_patches("myfunc", "newfp")
        assert pruned == 0
