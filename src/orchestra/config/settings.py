from __future__ import annotations

import os
from pathlib import Path

import yaml
from pydantic import BaseModel


class CxdbConfig(BaseModel):
    url: str = "http://localhost:9010"


class OrchestraConfig(BaseModel):
    cxdb: CxdbConfig = CxdbConfig()


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
    else:
        config = OrchestraConfig()

    cxdb_url_env = os.environ.get("ORCHESTRA_CXDB_URL")
    if cxdb_url_env is not None:
        config.cxdb.url = cxdb_url_env

    return config
