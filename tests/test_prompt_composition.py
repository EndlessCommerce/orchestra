import pytest

from orchestra.config.settings import AgentConfig
from orchestra.prompts.engine import compose_prompt


class TestPromptComposition:
    def test_single_layer_role_only(self, tmp_path):
        (tmp_path / "role.yaml").write_text("content: You are a code reviewer.")
        agent = AgentConfig(role="role.yaml")
        result = compose_prompt(agent, pipeline_dir=tmp_path)
        assert result == "You are a code reviewer."

    def test_all_four_layers(self, tmp_path):
        (tmp_path / "role.yaml").write_text("content: You are an engineer.")
        (tmp_path / "persona.yaml").write_text("content: You are senior-level.")
        (tmp_path / "personality.yaml").write_text("content: You are thorough.")
        (tmp_path / "task.yaml").write_text("content: Review the code.")
        agent = AgentConfig(
            role="role.yaml",
            persona="persona.yaml",
            personality="personality.yaml",
            task="task.yaml",
        )
        result = compose_prompt(agent, pipeline_dir=tmp_path)
        assert result == (
            "You are an engineer.\n\n"
            "You are senior-level.\n\n"
            "You are thorough.\n\n"
            "Review the code."
        )

    def test_jinja2_interpolation_in_task(self, tmp_path):
        (tmp_path / "task.yaml").write_text("content: Review this diff:\\n{{ pr_diff }}")
        agent = AgentConfig(task="task.yaml")
        result = compose_prompt(
            agent,
            context={"pr_diff": "+added line\n-removed line"},
            pipeline_dir=tmp_path,
        )
        assert "+added line" in result
        assert "-removed line" in result

    def test_missing_layer_skipped(self, tmp_path):
        (tmp_path / "role.yaml").write_text("content: You are an engineer.")
        (tmp_path / "task.yaml").write_text("content: Write code.")
        agent = AgentConfig(
            role="role.yaml",
            persona="",
            personality="",
            task="task.yaml",
        )
        result = compose_prompt(agent, pipeline_dir=tmp_path)
        assert result == "You are an engineer.\n\nWrite code."

    def test_missing_file_skipped(self, tmp_path):
        (tmp_path / "role.yaml").write_text("content: You are an engineer.")
        agent = AgentConfig(
            role="role.yaml",
            persona="nonexistent.yaml",
        )
        result = compose_prompt(agent, pipeline_dir=tmp_path)
        assert result == "You are an engineer."

    def test_empty_agent_returns_empty(self):
        agent = AgentConfig()
        result = compose_prompt(agent)
        assert result == ""

    def test_jinja2_strict_undefined_raises(self, tmp_path):
        (tmp_path / "task.yaml").write_text("content: Hello {{ missing_var }}")
        agent = AgentConfig(task="task.yaml")
        with pytest.raises(Exception):
            compose_prompt(agent, context={}, pipeline_dir=tmp_path)

    def test_multiline_yaml_content(self, tmp_path):
        (tmp_path / "role.yaml").write_text(
            "content: |\n"
            "  Line one.\n"
            "  Line two.\n"
        )
        agent = AgentConfig(role="role.yaml")
        result = compose_prompt(agent, pipeline_dir=tmp_path)
        assert "Line one." in result
        assert "Line two." in result

    def test_prompt_snapshot(self, tmp_path):
        (tmp_path / "role.yaml").write_text("content: You are an AI assistant.")
        (tmp_path / "persona.yaml").write_text("content: You prefer concise answers.")
        (tmp_path / "task.yaml").write_text('content: "Summarize: {{ topic }}"')
        agent = AgentConfig(
            role="role.yaml",
            persona="persona.yaml",
            task="task.yaml",
        )
        result = compose_prompt(
            agent,
            context={"topic": "machine learning"},
            pipeline_dir=tmp_path,
        )
        expected = (
            "You are an AI assistant.\n\n"
            "You prefer concise answers.\n\n"
            "Summarize: machine learning"
        )
        assert result == expected
