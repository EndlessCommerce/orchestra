from __future__ import annotations

from pathlib import Path
from typing import Any

import jinja2

from orchestra.config.file_discovery import discover_file
from orchestra.config.settings import AgentConfig
from orchestra.prompts.loader import load_prompt_layer

LAYER_ORDER = ["role", "persona", "personality", "task"]


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
            content = template.render(**context)

        layers.append(content)

    return "\n\n".join(layers)
