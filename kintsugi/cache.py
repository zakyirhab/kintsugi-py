"""
Patch Cache & Cold Start Rehydration for KintsugiPy.
Saves and loads validated patches to disk (.kintsugi_cache/) for zero-token re-runs.
Includes AST-aware fingerprinting, auto-.gitignore, machine-secret HMAC integrity checks,
and stale cache pruning with strict fail-closed tamper-evident verification.
"""

import ast
import hashlib
import hmac
import json
import logging
import os
from pathlib import Path
import secrets
from typing import Any, Dict, Optional

from kintsugi.sandbox import verify_code_safety

logger = logging.getLogger("kintsugi.cache")

_RESOLVED_SECRET: Optional[str] = None
_IS_PERSISTENT_SECRET: bool = False


def reset_cache_secret() -> None:
    """Reset cached secret in memory (primarily for unit testing)."""
    global _RESOLVED_SECRET, _IS_PERSISTENT_SECRET
    _RESOLVED_SECRET = None
    _IS_PERSISTENT_SECRET = False


def is_persistent_secret() -> bool:
    """Check whether the active HMAC secret is persistent across process restarts."""
    global _RESOLVED_SECRET
    if _RESOLVED_SECRET is None:
        get_cache_secret()
    return _IS_PERSISTENT_SECRET


def get_cache_secret() -> str:
    """Resolve HMAC secret key from environment or secure machine-local keyfile.
    
    Caches the secret in memory to avoid repeated disk reads.
    Enforces atomic creation (via 0600 tempfile + os.link/replace) and POSIX permission checks.
    Falls back to ephemeral secret (with disk caching disabled) if filesystem is read-only.
    """
    global _RESOLVED_SECRET, _IS_PERSISTENT_SECRET
    if _RESOLVED_SECRET is not None:
        return _RESOLVED_SECRET

    # 1. User-supplied environment variable (Highest Priority)
    env_secret = os.getenv("KINTSUGI_CACHE_SECRET")
    if env_secret and len(env_secret.strip()) >= 16:
        _RESOLVED_SECRET = env_secret.strip()
        _IS_PERSISTENT_SECRET = True
        return _RESOLVED_SECRET

    # 2. Machine-local private secret file in user home directory
    try:
        home_dir = Path.home()
        secret_file = home_dir / ".kintsugi_machine_secret"

        if secret_file.exists():
            # POSIX permission & ownership checks
            if os.name == "posix":
                stat_info = secret_file.stat()
                if stat_info.st_uid != os.getuid():
                    logger.warning(
                        "[Kintsugi] Secret file '%s' is not owned by current user (uid %d != %d). Rejecting.",
                        secret_file,
                        stat_info.st_uid,
                        os.getuid(),
                    )
                    raise PermissionError("Insecure secret file ownership")
                if (stat_info.st_mode & 0o077) != 0:
                    logger.warning(
                        "[Kintsugi] Secret file '%s' has too permissive mode (%o). Expected 0600.",
                        secret_file,
                        stat_info.st_mode & 0o777,
                    )
                    raise PermissionError("Insecure secret file permissions")

            content = secret_file.read_text(encoding="utf-8").strip()
            if len(content) >= 32:
                _RESOLVED_SECRET = content
                _IS_PERSISTENT_SECRET = True
                return _RESOLVED_SECRET

        # File does not exist or was empty/corrupt: Create atomically
        generated = secrets.token_hex(32)
        tmp_file = home_dir / f".kintsugi_machine_secret.tmp.{os.getpid()}.{secrets.token_hex(4)}"
        try:
            fd = os.open(str(tmp_file), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                f.write(generated)

            # Atomic link / replace
            if hasattr(os, "link"):
                try:
                    os.link(str(tmp_file), str(secret_file))
                except FileExistsError:
                    pass  # Concurrent process created it
            else:
                if not secret_file.exists():
                    os.replace(str(tmp_file), str(secret_file))
        finally:
            if tmp_file.exists():
                try:
                    tmp_file.unlink()
                except Exception:
                    pass

        if secret_file.exists():
            content = secret_file.read_text(encoding="utf-8").strip()
            if len(content) >= 32:
                _RESOLVED_SECRET = content
                _IS_PERSISTENT_SECRET = True
                return _RESOLVED_SECRET

    except Exception as e:
        logger.debug("[Kintsugi] Could not resolve or persist machine secret: %s", e)

    # 3. In-process ephemeral secret fallback
    _RESOLVED_SECRET = secrets.token_hex(32)
    _IS_PERSISTENT_SECRET = False
    logger.warning(
        "[Kintsugi] Persistent cache secret could not be established (filesystem may be read-only). "
        "Disk patch caching across restarts is disabled to prevent unverified cache loads. "
        "Set the 'KINTSUGI_CACHE_SECRET' environment variable to enable persistent caching."
    )
    return _RESOLVED_SECRET


def compute_fingerprint(func_name: str, source_code: str) -> str:
    """Compute a deterministic hash for a function based on its AST structure.
    
    Ignores comments, indentation variations, and formatting so that minor edits
    do not cause false cache misses, while actual logic changes cleanly invalidate the cache.
    """
    try:
        tree = ast.parse(source_code)
        normalized = ast.dump(tree, annotate_fields=False, include_attributes=False)
        raw = f"{func_name}::{normalized}"
    except Exception:
        raw = f"{func_name}::{source_code.strip()}"

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


def compute_patch_checksum(
    func_name: str,
    fingerprint: str,
    code: str,
    secret: Optional[str] = None,
) -> str:
    """Compute an HMAC-SHA256 checksum binding func_name, fingerprint, and code together."""
    sec = secret or get_cache_secret()
    payload = f"{func_name}:{fingerprint}:{code}"
    return hmac.new(sec.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


class PatchCache:
    """Manages reading, writing, tamper-evident verification, and pruning healed patches on disk."""

    def __init__(self, cache_dir: Optional[str] = ".kintsugi_cache") -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir and self.is_enabled():
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_gitignore()

    def is_enabled(self) -> bool:
        if self.cache_dir is None:
            return False
        # If no persistent secret could be established, disable disk caching
        get_cache_secret()
        if not is_persistent_secret():
            return False
        return True

    def _ensure_gitignore(self) -> None:
        """Ensure .kintsugi_cache directory contains a .gitignore file so patches are not committed."""
        if not self.cache_dir:
            return
        gi_file = self.cache_dir / ".gitignore"
        if not gi_file.exists():
            try:
                gi_file.write_text("*\n", encoding="utf-8")
            except Exception:
                pass

    def _get_patch_file(self, func_name: str, fingerprint: str) -> Path:
        return self.cache_dir / f"{func_name}_{fingerprint}.py"

    def _get_meta_file(self, func_name: str, fingerprint: str) -> Path:
        return self.cache_dir / f"{func_name}_{fingerprint}.json"

    def load_patch(
        self,
        func_name: str,
        fingerprint: str,
        original_source: Optional[str] = None,
    ) -> Optional[str]:
        """Load code patch from disk if it exists, passes HMAC integrity, and passes AST guardrails.
        
        Strict fail-closed policy: If the metadata or checksum is absent or invalid, the patch is rejected.
        If the patch contains placeholder secrets, they must cleanly resolve against current source code;
        otherwise the patch is safely rejected.
        """
        if not self.is_enabled():
            return None

        # Clean up any stale patches
        self.prune_stale_patches(func_name, fingerprint)

        patch_file = self._get_patch_file(func_name, fingerprint)
        meta_file = self._get_meta_file(func_name, fingerprint)

        if patch_file.exists():
            try:
                # Fail-closed: Metadata file MUST exist
                if not meta_file.exists():
                    logger.warning(
                        "[Kintsugi] Missing metadata file for '%s'. Rejecting unverified patch.",
                        func_name,
                    )
                    return None

                meta = json.loads(meta_file.read_text(encoding="utf-8"))
                expected_checksum = meta.get("checksum")
                if not expected_checksum:
                    logger.warning(
                        "[Kintsugi] Missing checksum in metadata for '%s'. Rejecting patch.",
                        func_name,
                    )
                    return None

                code = patch_file.read_text(encoding="utf-8")
                actual_checksum = compute_patch_checksum(func_name, fingerprint, code)

                if not hmac.compare_digest(expected_checksum, actual_checksum):
                    logger.warning(
                        "[Kintsugi] Cache integrity mismatch for '%s'. Rejecting tampered/transposed patch.",
                        func_name,
                    )
                    return None

                # Rehydration of secret placeholders with fail-closed validation
                if "__KINTSUGI_SECRET_" in code:
                    from kintsugi.privacy import map_and_replace_secrets, restore_mapped_secrets

                    expected_ph_count = meta.get("placeholder_count", 0)
                    if not original_source:
                        logger.warning(
                            "[Kintsugi] Cache rehydration for '%s' rejected: missing original source to resolve placeholder secrets.",
                            func_name,
                        )
                        return None

                    _, secret_map = map_and_replace_secrets(original_source)
                    if len(secret_map) != expected_ph_count or not secret_map:
                        logger.warning(
                            "[Kintsugi] Cache rehydration for '%s' rejected: placeholder secrets could not be resolved from current source. Falling back to original function.",
                            func_name,
                        )
                        return None

                    try:
                        code = restore_mapped_secrets(code, secret_map, original_source=original_source)
                    except Exception as e:
                        logger.warning(
                            "[Kintsugi] Cache rehydration for '%s' rejected: failed to safely restore secrets: %s",
                            func_name,
                            e,
                        )
                        return None

                # Defense-in-depth: Re-verify code safety through AST guardrail
                verify_code_safety(code, func_name)
                return code

            except Exception as e:
                logger.warning("[Kintsugi] Failed to load/verify cached patch for '%s': %s", func_name, e)
                return None

        return None

    def save_patch(
        self,
        func_name: str,
        fingerprint: str,
        code: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Save healed code patch and metadata with HMAC integrity to disk."""
        if not self.is_enabled():
            return False

        try:
            from kintsugi.privacy import redact_sensitive_text

            self.prune_stale_patches(func_name, fingerprint)

            patch_file = self._get_patch_file(func_name, fingerprint)
            patch_file.write_text(code, encoding="utf-8")

            meta = dict(metadata or {})
            if "original_error" in meta:
                meta["original_error"] = redact_sensitive_text(str(meta["original_error"]))

            meta["checksum"] = compute_patch_checksum(func_name, fingerprint, code)
            meta["fingerprint"] = fingerprint
            meta["func_name"] = func_name

            meta_file = self._get_meta_file(func_name, fingerprint)
            meta_file.write_text(json.dumps(meta, indent=2), encoding="utf-8")
            return True

        except Exception as e:
            logger.warning("[Kintsugi] Failed to write cache patch: %s", e)
            return False

    def prune_stale_patches(self, func_name: str, current_fingerprint: str) -> int:
        """Delete older cache files for func_name that do not match current_fingerprint."""
        if not self.is_enabled():
            return 0

        pruned = 0
        try:
            prefix = f"{func_name}_"
            valid_patch = f"{func_name}_{current_fingerprint}.py"
            valid_meta = f"{func_name}_{current_fingerprint}.json"

            for file_path in self.cache_dir.glob(f"{prefix}*"):
                if file_path.is_file() and file_path.name not in (valid_patch, valid_meta):
                    try:
                        file_path.unlink()
                        pruned += 1
                        logger.debug("[Kintsugi] Pruned stale cache file: %s", file_path.name)
                    except Exception:
                        pass
        except Exception:
            pass

        return pruned
