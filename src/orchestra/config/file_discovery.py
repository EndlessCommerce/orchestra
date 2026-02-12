from __future__ import annotations

from pathlib import Path


def discover_file(
    filename: str,
    pipeline_dir: Path | None = None,
    config_paths: list[str] | None = None,
    global_dir: Path | None = None,
) -> Path:
    searched: list[str] = []

    if pipeline_dir is not None:
        candidate = pipeline_dir / filename
        searched.append(str(candidate))
        if candidate.is_file():
            return candidate

    for config_path in config_paths or []:
        candidate = Path(config_path) / filename
        searched.append(str(candidate))
        if candidate.is_file():
            return candidate

    global_dir = global_dir or Path.home() / ".orchestra"
    candidate = global_dir / filename
    searched.append(str(candidate))
    if candidate.is_file():
        return candidate

    raise FileNotFoundError(
        f"Could not find '{filename}'. Searched:\n"
        + "\n".join(f"  - {s}" for s in searched)
    )
