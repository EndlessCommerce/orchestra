from pathlib import Path

import pytest

from orchestra.config.settings import (
    AgentConfig,
    CxdbConfig,
    OrchestraConfig,
    ProviderConfig,
    ProvidersConfig,
    ToolConfig,
    load_config,
)


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


class TestProvidersConfig:
    def test_full_providers_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "providers:\n"
            "  default: anthropic\n"
            "  anthropic:\n"
            "    models:\n"
            "      smart: claude-opus-4-20250514\n"
            "      worker: claude-sonnet-4-20250514\n"
            "      cheap: claude-haiku-3-20250514\n"
            "    settings:\n"
            "      max_tokens: 4096\n"
            "  openai:\n"
            "    models:\n"
            "      smart: gpt-4o\n"
            "      worker: gpt-4o-mini\n"
        )
        config = load_config(start=tmp_path)
        assert config.providers.default == "anthropic"
        assert config.providers.anthropic.models["smart"] == "claude-opus-4-20250514"
        assert config.providers.anthropic.settings["max_tokens"] == 4096
        assert config.providers.openai.models["smart"] == "gpt-4o"

    def test_default_providers(self) -> None:
        config = OrchestraConfig()
        assert config.providers.default == ""
        assert config.providers.anthropic.models == {}

    def test_provider_config_construction(self) -> None:
        pc = ProviderConfig(
            models={"smart": "gpt-4o", "cheap": "gpt-4o-mini"},
            settings={"api_base": "https://custom.api"},
        )
        assert pc.models["smart"] == "gpt-4o"
        assert pc.settings["api_base"] == "https://custom.api"


class TestAgentConfig:
    def test_full_agent_config(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "agents:\n"
            "  code-reviewer:\n"
            "    role: roles/code-reviewer.yaml\n"
            "    persona: personas/senior-engineer.yaml\n"
            "    personality: personalities/thorough.yaml\n"
            "    task: tasks/review-code.yaml\n"
            "    tools:\n"
            "      - read-file\n"
            "      - search-code\n"
            "    provider: anthropic\n"
            "    model: smart\n"
        )
        config = load_config(start=tmp_path)
        agent = config.agents["code-reviewer"]
        assert agent.role == "roles/code-reviewer.yaml"
        assert agent.persona == "personas/senior-engineer.yaml"
        assert agent.tools == ["read-file", "search-code"]
        assert agent.provider == "anthropic"
        assert agent.model == "smart"

    def test_minimal_agent_config(self) -> None:
        agent = AgentConfig(role="roles/basic.yaml")
        assert agent.role == "roles/basic.yaml"
        assert agent.persona == ""
        assert agent.tools == []

    def test_multiple_agents(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "agents:\n"
            "  writer:\n"
            "    role: roles/writer.yaml\n"
            "  reviewer:\n"
            "    role: roles/reviewer.yaml\n"
        )
        config = load_config(start=tmp_path)
        assert "writer" in config.agents
        assert "reviewer" in config.agents


class TestToolConfig:
    def test_tool_config_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "tools:\n"
            "  - name: run-tests\n"
            "    command: pytest tests/\n"
            "    description: Run the test suite\n"
            "  - name: lint\n"
            "    command: ruff check .\n"
        )
        config = load_config(start=tmp_path)
        assert len(config.tools) == 2
        assert config.tools[0].name == "run-tests"
        assert config.tools[0].command == "pytest tests/"
        assert config.tools[0].description == "Run the test suite"
        assert config.tools[1].name == "lint"

    def test_tool_config_construction(self) -> None:
        tool = ToolConfig(name="my-tool", command="echo hello")
        assert tool.name == "my-tool"
        assert tool.command == "echo hello"


class TestBackendConfig:
    def test_default_backend(self) -> None:
        config = OrchestraConfig()
        assert config.backend == "simulation"

    def test_backend_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text("backend: langgraph\n")
        config = load_config(start=tmp_path)
        assert config.backend == "langgraph"


class TestConfigValidation:
    def test_invalid_agent_field_rejected(self) -> None:
        with pytest.raises(Exception):
            AgentConfig(tools="not-a-list")  # type: ignore[arg-type]

    def test_unknown_fields_ignored(self) -> None:
        config = OrchestraConfig.model_validate({"nonexistent_field": "value"})
        assert config.backend == "simulation"

    def test_full_config_roundtrip(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "cxdb:\n"
            "  url: http://test:9010\n"
            "providers:\n"
            "  default: anthropic\n"
            "  anthropic:\n"
            "    models:\n"
            "      smart: claude-opus-4-20250514\n"
            "agents:\n"
            "  coder:\n"
            "    role: roles/coder.yaml\n"
            "    tools:\n"
            "      - write-file\n"
            "tools:\n"
            "  - name: deploy\n"
            "    command: ./deploy.sh\n"
            "backend: direct\n"
        )
        config = load_config(start=tmp_path)
        assert config.cxdb.url == "http://test:9010"
        assert config.providers.default == "anthropic"
        assert config.agents["coder"].role == "roles/coder.yaml"
        assert config.tools[0].name == "deploy"
        assert config.backend == "direct"
