"""
Patch Cache & Cold Start Rehydration for KintsugiPy.
Saves and loads validated patches to disk (.kintsugi_cache/) for zero-token re-runs.
Includes AST-aware fingerprinting, auto-.gitignore, machine-secret HMAC integrity checks,
and stale cache pruning with strict fail-closed verification.
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


def get_cache_secret() -> str:
    """Resolve HMAC secret key from environment or secure machine-local keyfile."""
    # 1. User-supplied environment variable
    env_secret = os.getenv("KINTSUGI_CACHE_SECRET")
    if env_secret:
        return env_secret

    # 2. Machine-local private secret file in user home directory
    try:
        secret_file = Path.home() / ".kintsugi_machine_secret"
        if secret_file.exists():
            return secret_file.read_text(encoding="utf-8").strip()
        else:
            generated = secrets.token_hex(32)
            try:
                secret_file.write_text(generated, encoding="utf-8")
                if os.name == "posix":
                    os.chmod(secret_file, 0o600)
            except Exception:
                pass
            return generated
    except Exception:
        pass

    # 3. In-process ephemeral secret fallback
    if not hasattr(get_cache_secret, "_ephemeral"):
        get_cache_secret._ephemeral = secrets.token_hex(32)  # type: ignore[attr-defined]
    return get_cache_secret._ephemeral  # type: ignore[attr-defined]


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
    """Manages reading, writing, integrity verification, and pruning healed patches on disk."""

    def __init__(self, cache_dir: Optional[str] = ".kintsugi_cache") -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)
            self._ensure_gitignore()

    def is_enabled(self) -> bool:
        return self.cache_dir is not None

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

    def load_patch(self, func_name: str, fingerprint: str) -> Optional[str]:
        """Load code patch from disk if it exists, passes HMAC integrity, and passes AST guardrails.
        
        Strict fail-closed policy: If the metadata or checksum is absent or invalid, the patch is rejected.
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
            self.prune_stale_patches(func_name, fingerprint)

            patch_file = self._get_patch_file(func_name, fingerprint)
            patch_file.write_text(code, encoding="utf-8")

            meta = dict(metadata or {})
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
