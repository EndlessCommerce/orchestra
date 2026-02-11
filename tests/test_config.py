from pathlib import Path

from orchestra.config.settings import CxdbConfig, OrchestraConfig, load_config


def test_loads_from_cwd(tmp_path: Path) -> None:
    config_file = tmp_path / "orchestra.yaml"
    config_file.write_text("cxdb:\n  url: http://custom:1234\n")
    config = load_config(start=tmp_path)
    assert config.cxdb.url == "http://custom:1234"


def test_walks_parent_directories(tmp_path: Path) -> None:
    config_file = tmp_path / "orchestra.yaml"
    config_file.write_text("cxdb:\n  url: http://parent:5678\n")
    child = tmp_path / "a" / "b" / "c"
    child.mkdir(parents=True)
    config = load_config(start=child)
    assert config.cxdb.url == "http://parent:5678"


def test_falls_back_to_defaults(tmp_path: Path) -> None:
    child = tmp_path / "no_config_here"
    child.mkdir()
    config = load_config(start=child)
    assert config.cxdb.url == "http://localhost:9010"


def test_validates_pydantic_model() -> None:
    config = OrchestraConfig(cxdb=CxdbConfig(url="http://test:9999"))
    assert config.cxdb.url == "http://test:9999"


def test_env_var_overrides_yaml(tmp_path: Path, monkeypatch: object) -> None:
    config_file = tmp_path / "orchestra.yaml"
    config_file.write_text("cxdb:\n  url: http://yaml:1111\n")
    monkeypatch.setenv("ORCHESTRA_CXDB_URL", "http://env:2222")  # type: ignore[attr-defined]
    config = load_config(start=tmp_path)
    assert config.cxdb.url == "http://env:2222"


def test_env_var_overrides_default(tmp_path: Path, monkeypatch: object) -> None:
    child = tmp_path / "no_config"
    child.mkdir()
    monkeypatch.setenv("ORCHESTRA_CXDB_URL", "http://env:3333")  # type: ignore[attr-defined]
    config = load_config(start=child)
    assert config.cxdb.url == "http://env:3333"
