from pathlib import Path

from orchestra.config.settings import (
    OrchestraConfig,
    RepoConfig,
    WorkspaceConfig,
    WorkspaceToolConfig,
    load_config,
)


class TestRepoConfig:
    def test_defaults(self) -> None:
        repo = RepoConfig(path="./my-project")
        assert repo.path == "./my-project"
        assert repo.branch_prefix == "orchestra/"
        assert repo.remote == ""
        assert repo.push == ""
        assert repo.clone_depth == 0

    def test_custom_prefix(self) -> None:
        repo = RepoConfig(path="/abs/path", branch_prefix="custom/")
        assert repo.branch_prefix == "custom/"


class TestWorkspaceConfig:
    def test_empty_workspace(self) -> None:
        ws = WorkspaceConfig()
        assert ws.repos == {}

    def test_single_repo(self) -> None:
        ws = WorkspaceConfig(
            repos={"project": RepoConfig(path="./my-project")}
        )
        assert "project" in ws.repos
        assert ws.repos["project"].path == "./my-project"

    def test_multi_repo(self) -> None:
        ws = WorkspaceConfig(
            repos={
                "backend": RepoConfig(path="/workspace/backend"),
                "frontend": RepoConfig(path="/workspace/frontend"),
            }
        )
        assert len(ws.repos) == 2
        assert ws.repos["backend"].path == "/workspace/backend"
        assert ws.repos["frontend"].path == "/workspace/frontend"


class TestOrchestraConfigWorkspace:
    def test_default_workspace_is_empty(self) -> None:
        config = OrchestraConfig()
        assert config.workspace.repos == {}

    def test_single_repo_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    project:\n"
            "      path: ./my-project\n"
            "      branch_prefix: orchestra/\n"
        )
        config = load_config(start=tmp_path)
        assert "project" in config.workspace.repos
        assert config.workspace.repos["project"].path == "./my-project"
        assert config.workspace.repos["project"].branch_prefix == "orchestra/"

    def test_multi_repo_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    backend:\n"
            "      path: /workspace/backend\n"
            "      branch_prefix: orchestra/\n"
            "    frontend:\n"
            "      path: /workspace/frontend\n"
            "      branch_prefix: custom/\n"
        )
        config = load_config(start=tmp_path)
        assert len(config.workspace.repos) == 2
        assert config.workspace.repos["backend"].path == "/workspace/backend"
        assert config.workspace.repos["frontend"].branch_prefix == "custom/"

    def test_empty_workspace_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text("workspace:\n  repos: {}\n")
        config = load_config(start=tmp_path)
        assert config.workspace.repos == {}

    def test_relative_path_resolution(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    project:\n"
            "      path: ./my-project\n"
        )
        config = load_config(start=tmp_path)
        assert config.config_dir == tmp_path
        repo_path = (config.config_dir / config.workspace.repos["project"].path).resolve()
        assert repo_path == (tmp_path / "my-project").resolve()

    def test_unknown_workspace_fields_ignored(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    project:\n"
            "      path: ./proj\n"
            "      remote: origin\n"
            "      push: auto\n"
            "      clone_depth: 1\n"
        )
        config = load_config(start=tmp_path)
        repo = config.workspace.repos["project"]
        assert repo.remote == "origin"
        assert repo.push == "auto"
        assert repo.clone_depth == 1

    def test_no_workspace_section(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text("backend: langgraph\n")
        config = load_config(start=tmp_path)
        assert config.workspace.repos == {}

    def test_workspace_tools_from_yaml(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    project:\n"
            "      path: ./my-project\n"
            "  tools:\n"
            "    project:\n"
            "      run-tests:\n"
            '        command: "python -m pytest -v"\n'
            '        description: "Run pytest"\n'
            "      lint:\n"
            '        command: "ruff check ."\n'
        )
        config = load_config(start=tmp_path)
        assert "project" in config.workspace.tools
        assert "run-tests" in config.workspace.tools["project"]
        assert config.workspace.tools["project"]["run-tests"].command == "python -m pytest -v"
        assert config.workspace.tools["project"]["run-tests"].description == "Run pytest"
        assert config.workspace.tools["project"]["lint"].command == "ruff check ."

    def test_workspace_tools_default_empty(self) -> None:
        ws = WorkspaceConfig()
        assert ws.tools == {}

    def test_workspace_tools_multi_repo(self, tmp_path: Path) -> None:
        config_file = tmp_path / "orchestra.yaml"
        config_file.write_text(
            "workspace:\n"
            "  repos:\n"
            "    backend:\n"
            "      path: ./backend\n"
            "    frontend:\n"
            "      path: ./frontend\n"
            "  tools:\n"
            "    backend:\n"
            "      run-tests:\n"
            '        command: "bundle exec rspec"\n'
            "    frontend:\n"
            "      run-tests:\n"
            '        command: "npm test"\n'
        )
        config = load_config(start=tmp_path)
        assert config.workspace.tools["backend"]["run-tests"].command == "bundle exec rspec"
        assert config.workspace.tools["frontend"]["run-tests"].command == "npm test"
