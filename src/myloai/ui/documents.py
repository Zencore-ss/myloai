from __future__ import annotations

import sys
from pathlib import Path


def bundled_document_path(name: str) -> Path:
    """Resolve a bundled documentation file for frozen builds and source checkouts."""
    candidates: list[Path] = []
    frozen_root = getattr(sys, "_MEIPASS", "")
    if frozen_root:
        candidates.append(Path(frozen_root) / "docs" / name)
        candidates.append(Path(frozen_root) / "packaging" / name)
    repo_root = Path(__file__).resolve().parents[3]
    candidates.append(repo_root / "docs" / name)
    candidates.append(repo_root / "packaging" / name)
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[-1]
