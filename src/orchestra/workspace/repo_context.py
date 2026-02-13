from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class RepoContext:
    name: str
    path: Path
    branch: str
    base_sha: str
    worktree_path: Path | None = None
