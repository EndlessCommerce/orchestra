import pytest

from orchestra.config.file_discovery import discover_file


class TestFileDiscovery:
    def test_pipeline_relative(self, tmp_path):
        pipeline_dir = tmp_path / "pipelines"
        pipeline_dir.mkdir()
        (pipeline_dir / "role.yaml").write_text("content: test")
        result = discover_file("role.yaml", pipeline_dir=pipeline_dir)
        assert result == pipeline_dir / "role.yaml"

    def test_project_config_path(self, tmp_path):
        config_dir = tmp_path / "prompts"
        config_dir.mkdir()
        (config_dir / "role.yaml").write_text("content: test")
        result = discover_file("role.yaml", config_paths=[str(config_dir)])
        assert result == config_dir / "role.yaml"

    def test_global_fallback(self, tmp_path):
        global_dir = tmp_path / ".orchestra"
        global_dir.mkdir()
        (global_dir / "role.yaml").write_text("content: test")
        result = discover_file("role.yaml", global_dir=global_dir)
        assert result == global_dir / "role.yaml"

    def test_pipeline_relative_takes_precedence(self, tmp_path):
        pipeline_dir = tmp_path / "pipelines"
        pipeline_dir.mkdir()
        (pipeline_dir / "role.yaml").write_text("pipeline version")

        config_dir = tmp_path / "prompts"
        config_dir.mkdir()
        (config_dir / "role.yaml").write_text("config version")

        result = discover_file(
            "role.yaml",
            pipeline_dir=pipeline_dir,
            config_paths=[str(config_dir)],
        )
        assert result == pipeline_dir / "role.yaml"

    def test_config_path_takes_precedence_over_global(self, tmp_path):
        config_dir = tmp_path / "prompts"
        config_dir.mkdir()
        (config_dir / "role.yaml").write_text("config version")

        global_dir = tmp_path / ".orchestra"
        global_dir.mkdir()
        (global_dir / "role.yaml").write_text("global version")

        result = discover_file(
            "role.yaml",
            config_paths=[str(config_dir)],
            global_dir=global_dir,
        )
        assert result == config_dir / "role.yaml"

    def test_not_found_raises_with_locations(self, tmp_path):
        with pytest.raises(FileNotFoundError, match="Could not find 'missing.yaml'"):
            discover_file(
                "missing.yaml",
                pipeline_dir=tmp_path / "pipeline",
                config_paths=[str(tmp_path / "config")],
                global_dir=tmp_path / ".orchestra",
            )

    def test_not_found_lists_searched_paths(self, tmp_path):
        with pytest.raises(FileNotFoundError) as exc_info:
            discover_file(
                "missing.yaml",
                pipeline_dir=tmp_path / "pipeline",
                global_dir=tmp_path / ".orchestra",
            )
        msg = str(exc_info.value)
        assert "pipeline" in msg
        assert ".orchestra" in msg

    def test_multiple_config_paths(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()
        (dir_b / "role.yaml").write_text("from b")

        result = discover_file(
            "role.yaml",
            config_paths=[str(dir_a), str(dir_b)],
        )
        assert result == dir_b / "role.yaml"
