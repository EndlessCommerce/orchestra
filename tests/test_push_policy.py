from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from orchestra.config.settings import RepoConfig


class TestEffectivePushPolicy:
    def test_default_push_with_remote(self) -> None:
        """Remote set, no push → on_completion."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git")
        assert config.effective_push_policy == "on_completion"

    def test_default_push_without_remote(self) -> None:
        """No remote → never."""
        config = RepoConfig(path="/tmp/repo")
        assert config.effective_push_policy == "never"

    def test_explicit_push_override(self) -> None:
        """Explicit push: never with remote → never."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git", push="never")
        assert config.effective_push_policy == "never"

    def test_explicit_on_checkpoint(self) -> None:
        """Explicit push: on_checkpoint."""
        config = RepoConfig(path="/tmp/repo", remote="git@github.com:org/repo.git", push="on_checkpoint")
        assert config.effective_push_policy == "on_checkpoint"

    def test_explicit_on_completion_without_remote(self) -> None:
        """Explicit push: on_completion even without remote (user knows best)."""
        config = RepoConfig(path="/tmp/repo", push="on_completion")
        assert config.effective_push_policy == "on_completion"
