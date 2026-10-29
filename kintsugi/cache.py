"""
Patch Cache & Cold Start Rehydration for KintsugiPy.
Saves and loads validated patches to disk (.kintsugi_cache/) for zero-token re-runs.
"""

import hashlib
import json
import os
from pathlib import Path
from typing import Any, Dict, Optional


def compute_fingerprint(func_name: str, source_code: str) -> str:
    """Compute a deterministic hash for a function based on its name and original source."""
    raw = f"{func_name}::{source_code.strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:16]


class PatchCache:
    """Manages reading and writing healed patches to disk."""

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
        """Load code patch from disk if it exists."""
        if not self.is_enabled():
            return None

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
        """Save healed code patch and metadata to disk."""
        if not self.is_enabled():
            return False

        try:
            patch_file = self._get_patch_file(func_name, fingerprint)
            patch_file.write_text(code, encoding="utf-8")

            if metadata:
                meta_file = self._get_meta_file(func_name, fingerprint)
                meta_file.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
            return True
        except Exception:
            return False
