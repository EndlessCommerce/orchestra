from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field


class CxdbConfig(BaseModel):
    url: str = "http://localhost:9010"


class ProviderConfig(BaseModel):
    models: dict[str, str] = Field(default_factory=dict)
    settings: dict[str, Any] = Field(default_factory=dict)


class ProvidersConfig(BaseModel):
    default: str = ""
    anthropic: ProviderConfig = ProviderConfig()
    openai: ProviderConfig = ProviderConfig()
    openrouter: ProviderConfig = ProviderConfig()


class AgentConfig(BaseModel):
    role: str = ""
    persona: str = ""
    personality: str = ""
    task: str = ""
    tools: list[str] = Field(default_factory=list)
    provider: str = ""
    model: str = ""


class ToolConfig(BaseModel):
    name: str
    command: str = ""
    description: str = ""


class RepoConfig(BaseModel):
    path: str
    branch_prefix: str = "orchestra/"
    remote: str = ""
    push: str = ""
    clone_depth: int = 0


class WorkspaceToolConfig(BaseModel):
    command: str
    description: str = ""


class WorkspaceConfig(BaseModel):
    repos: dict[str, RepoConfig] = Field(default_factory=dict)
    tools: dict[str, dict[str, WorkspaceToolConfig]] = Field(default_factory=dict)


class OrchestraConfig(BaseModel):
    cxdb: CxdbConfig = CxdbConfig()
    providers: ProvidersConfig = ProvidersConfig()
    agents: dict[str, AgentConfig] = Field(default_factory=dict)
    tools: list[ToolConfig] = Field(default_factory=list)
    workspace: WorkspaceConfig = WorkspaceConfig()
    backend: str = "simulation"
    recursion_limit: int = 1000
    config_dir: Path | None = None


def _find_config_file(start: Path | None = None) -> Path | None:
    current = (start or Path.cwd()).resolve()
    while True:
        candidate = current / "orchestra.yaml"
        if candidate.is_file():
            return candidate
        parent = current.parent
        if parent == current:
            break
        current = parent
    return None


def load_config(start: Path | None = None) -> OrchestraConfig:
    config_path = _find_config_file(start)

    if config_path is not None:
        with open(config_path) as f:
            raw = yaml.safe_load(f) or {}
        config = OrchestraConfig.model_validate(raw)
        config.config_dir = config_path.parent
    else:
        config = OrchestraConfig()

    cxdb_url_env = os.environ.get("ORCHESTRA_CXDB_URL")
    if cxdb_url_env is not None:
        config.cxdb.url = cxdb_url_env

    return config
