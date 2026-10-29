"""
Patch Cache & Cold Start Rehydration for KintsugiPy.
Saves and loads validated patches to disk (.kintsugi_cache/) for zero-token re-runs.
Includes AST-aware fingerprinting and stale cache pruning.
"""

import ast
import hashlib
import json
import logging
from pathlib import Path
from typing import Any, Dict, Optional

logger = logging.getLogger("kintsugi.cache")


def compute_fingerprint(func_name: str, source_code: str) -> str:
    """Compute a deterministic hash for a function based on its AST structure.
    
    Ignores comments, indentation variations, and formatting so that minor edits
    do not cause false cache misses, while actual logic changes cleanly invalidate the cache.
    """
    try:
        tree = ast.parse(source_code)
        # ast.dump without line numbers/attributes ensures pure structural comparison
        normalized = ast.dump(tree, annotate_fields=False, include_attributes=False)
        raw = f"{func_name}::{normalized}"
    except Exception:
        # Fallback to trimmed text if AST parsing fails
        raw = f"{func_name}::{source_code.strip()}"

    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class PatchCache:
    """Manages reading, writing, and pruning healed patches on disk."""

    def __init__(self, cache_dir: Optional[str] = ".kintsugi_cache") -> None:
        self.cache_dir = Path(cache_dir) if cache_dir else None
        if self.cache_dir:
            self.cache_dir.mkdir(parents=True, exist_ok=True)

    def is_enabled(self) -> bool:
        return self.cache_dir is not None

    def _get_patch_file(self, func_name: str, fingerprint: str) -> Path:
        return self.cache_dir / f"{func_name}_{fingerprint}.py"

    def _get_meta_file(self, func_name: str, fingerprint: str) -> Path:
        return self.cache_dir / f"{func_name}_{fingerprint}.json"

    def load_patch(self, func_name: str, fingerprint: str) -> Optional[str]:
        """Load code patch from disk if it exists and matches the current fingerprint."""
        if not self.is_enabled():
            return None

        # Clean up any stale/orphaned patches from older versions of this function
        self.prune_stale_patches(func_name, fingerprint)

        patch_file = self._get_patch_file(func_name, fingerprint)
        if patch_file.exists():
            try:
                return patch_file.read_text(encoding="utf-8")
            except Exception:
                return None
        return None

    def save_patch(
        self,
        func_name: str,
        fingerprint: str,
        code: str,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> bool:
        """Save healed code patch and metadata to disk, pruning obsolete versions."""
        if not self.is_enabled():
            return False

        try:
            # Clean up older patches for this function
            self.prune_stale_patches(func_name, fingerprint)

            patch_file = self._get_patch_file(func_name, fingerprint)
            patch_file.write_text(code, encoding="utf-8")

            if metadata:
                meta_file = self._get_meta_file(func_name, fingerprint)
                meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
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
