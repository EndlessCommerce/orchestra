from __future__ import annotations

from pathlib import Path

import yaml


def load_prompt_layer(filepath: Path) -> str:
    raw = yaml.safe_load(filepath.read_text())
    if not isinstance(raw, dict):
        raise ValueError(f"Prompt file {filepath} must be a YAML mapping, got {type(raw).__name__}")
    if "content" not in raw:
        raise ValueError(f"Prompt file {filepath} missing required 'content' key")
    return str(raw["content"])
