from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2

from orchestra.config.file_discovery import discover_file
from orchestra.config.settings import AgentConfig
from orchestra.prompts.loader import load_prompt_layer

LAYER_ORDER = ["role", "persona", "personality", "task"]


def nest_dotted_keys(flat: dict[str, Any]) -> dict[str, Any]:
    """Convert flat dot-notation keys into nested dicts for Jinja2.

    ``{"tool.output": "x", "tool.exit_code": 0, "outcome": "ok"}``
    becomes ``{"tool": {"output": "x", "exit_code": 0}, "outcome": "ok"}``.

    Top-level (non-dotted) keys are preserved as-is.  If a dotted key
    conflicts with a non-dotted key of the same prefix, the nested dict
    wins (the flat scalar is overwritten).
    """
    nested: dict[str, Any] = {}
    for key, value in flat.items():
        parts = key.split(".")
        if len(parts) == 1:
            # Only set if not already occupied by a sub-dict from a dotted key
            if key not in nested or not isinstance(nested[key], dict):
                nested[key] = value
        else:
            d = nested
            for part in parts[:-1]:
                if part not in d or not isinstance(d[part], dict):
                    d[part] = {}
                d = d[part]
            d[parts[-1]] = value
    return nested


def compose_prompt(
    agent_config: AgentConfig,
    context: dict[str, Any] | None = None,
    pipeline_dir: Path | None = None,
    config_paths: list[str] | None = None,
) -> str:
    context = context or {}
    layers: list[str] = []

    for layer_name in LAYER_ORDER:
        filename = getattr(agent_config, layer_name, "")
        if not filename:
            continue

        try:
            filepath = discover_file(
                filename,
                pipeline_dir=pipeline_dir,
                config_paths=config_paths,
            )
        except FileNotFoundError:
            continue

        content = load_prompt_layer(filepath)

        if layer_name == "task":
            template = jinja2.Template(content, undefined=jinja2.StrictUndefined)
            content = template.render(**nest_dotted_keys(context))

        layers.append(content)

    return "\n\n".join(layers)
