from unittest.mock import MagicMock

import pytest

from orchestra.workspace.commit_message import (
    DeterministicCommitMessageGenerator,
    LLMCommitMessageGenerator,
    build_commit_message_generator,
)
from orchestra.workspace.session_branch import WorkspaceError


SAMPLE_DIFF = """\
diff --git a/src/main.py b/src/main.py
index abc1234..def5678 100644
--- a/src/main.py
+++ b/src/main.py
@@ -1,3 +1,5 @@
+import os
+
 def main():
-    pass
+    print("hello")
"""


class TestDeterministicCommitMessageGenerator:
    def test_generates_message(self) -> None:
        gen = DeterministicCommitMessageGenerator()
        msg = gen.generate(SAMPLE_DIFF, "Add hello world")
        assert msg.startswith("chore: auto-commit agent changes")
        assert "src/main.py" in msg

    def test_empty_diff(self) -> None:
        gen = DeterministicCommitMessageGenerator()
        msg = gen.generate("", "Nothing")
        assert "agent changes" in msg

    def test_multi_file_diff(self) -> None:
        multi_diff = (
            "diff --git a/a.py b/a.py\n+x\n"
            "diff --git a/b.py b/b.py\n+y\n"
        )
        gen = DeterministicCommitMessageGenerator()
        msg = gen.generate(multi_diff, "changes")
        assert "a.py" in msg
        assert "b.py" in msg


class TestLLMCommitMessageGenerator:
    def test_generates_from_model(self) -> None:
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "feat: add hello world output\n\nAdds a print statement to main."
        mock_model.invoke.return_value = mock_response

        gen = LLMCommitMessageGenerator(mock_model)
        msg = gen.generate(SAMPLE_DIFF, "Add hello world")

        assert msg == "feat: add hello world output\n\nAdds a print statement to main."
        mock_model.invoke.assert_called_once()

    def test_falls_back_on_empty_response(self) -> None:
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = ""
        mock_model.invoke.return_value = mock_response

        gen = LLMCommitMessageGenerator(mock_model)
        msg = gen.generate(SAMPLE_DIFF, "intent")
        assert "chore: auto-commit" in msg

    def test_falls_back_on_error(self) -> None:
        mock_model = MagicMock()
        mock_model.invoke.side_effect = RuntimeError("API down")

        gen = LLMCommitMessageGenerator(mock_model)
        msg = gen.generate(SAMPLE_DIFF, "intent")
        assert "chore: auto-commit" in msg

    def test_truncates_long_diff(self) -> None:
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "chore: update files"
        mock_model.invoke.return_value = mock_response

        gen = LLMCommitMessageGenerator(mock_model)
        long_diff = "x" * 10000
        gen.generate(long_diff, "intent")

        call_args = mock_model.invoke.call_args[0][0]
        prompt_content = call_args[0].content
        assert len(prompt_content) < 10000

    def test_summary_line_format(self) -> None:
        mock_model = MagicMock()
        mock_response = MagicMock()
        mock_response.content = "feat: short summary line\n\nBody text here."
        mock_model.invoke.return_value = mock_response

        gen = LLMCommitMessageGenerator(mock_model)
        msg = gen.generate(SAMPLE_DIFF, "intent")
        first_line = msg.split("\n")[0]
        assert len(first_line) <= 72


class TestBuildCommitMessageGenerator:
    def test_raises_without_cheap_alias(self) -> None:
        from orchestra.config.settings import OrchestraConfig

        config = OrchestraConfig()
        with pytest.raises(WorkspaceError, match="cheap"):
            build_commit_message_generator(config)

    def test_raises_with_no_provider(self) -> None:
        from orchestra.config.settings import OrchestraConfig, ProvidersConfig

        config = OrchestraConfig(providers=ProvidersConfig())
        with pytest.raises(WorkspaceError, match="cheap"):
            build_commit_message_generator(config)
