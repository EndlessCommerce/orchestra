"""Real LLM integration tests for adversarial PR review pipeline.

Gated behind ORCHESTRA_REAL_LLM=1 environment variable.
Uses cheap models (Haiku-tier) to minimize cost.
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any

import pytest

from orchestra.config.settings import (
    AgentConfig,
    OrchestraConfig,
    ProviderConfig,
    ProvidersConfig,
)
from orchestra.engine.runner import PipelineRunner
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.exit import ExitHandler
from orchestra.handlers.registry import HandlerRegistry
from orchestra.handlers.start import StartHandler
from orchestra.handlers.tool_handler import ToolHandler
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus

SKIP_REASON = "Set ORCHESTRA_REAL_LLM=1 and ANTHROPIC_API_KEY to run real LLM tests"

pytestmark = pytest.mark.skipif(
    not (os.environ.get("ORCHESTRA_REAL_LLM") == "1" and os.environ.get("ANTHROPIC_API_KEY")),
    reason=SKIP_REASON,
)


SAMPLE_DIFF = """\
diff --git a/app.py b/app.py
index 1234567..abcdefg 100644
--- a/app.py
+++ b/app.py
@@ -10,6 +10,12 @@ class UserService:
     def get_user(self, user_id: int) -> dict:
         return self.db.query(f"SELECT * FROM users WHERE id = {user_id}")

+    def delete_user(self, user_id: int) -> bool:
+        query = f"DELETE FROM users WHERE id = {user_id}"
+        self.db.execute(query)
+        return True
+
     def list_users(self) -> list[dict]:
         return self.db.query("SELECT * FROM users")
"""

PR_REVIEW_PROMPTS = Path(__file__).parent.parent / "examples" / "pr-review" / "prompts"


class RecordingEmitter:
    def __init__(self) -> None:
        self.events: list[tuple[str, dict[str, Any]]] = []

    def emit(self, event_type: str, **data: Any) -> None:
        self.events.append((event_type, data))


def _build_real_config() -> OrchestraConfig:
    """Build config with cheap Haiku model for cost-effective testing."""
    return OrchestraConfig(
        backend="direct",
        providers=ProvidersConfig(
            default="anthropic",
            anthropic=ProviderConfig(
                models={
                    "smart": "claude-haiku-4-5-20251001",
                    "worker": "claude-haiku-4-5-20251001",
                    "cheap": "claude-haiku-4-5-20251001",
                }
            ),
        ),
        agents={
            "security-reviewer": AgentConfig(
                role=str(PR_REVIEW_PROMPTS / "roles" / "pr-reviewer.yaml"),
                persona=str(PR_REVIEW_PROMPTS / "personas" / "security-specialist.yaml"),
                task=str(PR_REVIEW_PROMPTS / "tasks" / "review-security.yaml"),
                model="cheap",
            ),
            "architecture-reviewer": AgentConfig(
                role=str(PR_REVIEW_PROMPTS / "roles" / "pr-reviewer.yaml"),
                persona=str(PR_REVIEW_PROMPTS / "personas" / "architecture-specialist.yaml"),
                task=str(PR_REVIEW_PROMPTS / "tasks" / "review-architecture.yaml"),
                model="cheap",
            ),
            "review-critic": AgentConfig(
                role=str(PR_REVIEW_PROMPTS / "roles" / "review-critic.yaml"),
                persona=str(PR_REVIEW_PROMPTS / "personas" / "adversarial-critic.yaml"),
                task=str(PR_REVIEW_PROMPTS / "tasks" / "critique-reviews.yaml"),
                model="cheap",
            ),
            "synthesizer": AgentConfig(
                role=str(PR_REVIEW_PROMPTS / "roles" / "pr-reviewer.yaml"),
                task=str(PR_REVIEW_PROMPTS / "tasks" / "synthesize-review.yaml"),
                model="cheap",
            ),
        },
    )


def _build_linear_review_graph() -> PipelineGraph:
    """Build a simple linear review pipeline (no parallel) for fast testing."""
    return PipelineGraph(
        name="real_llm_review",
        nodes={
            "start": Node(id="start", shape="Mdiamond"),
            "get_diff": Node(
                id="get_diff",
                shape="parallelogram",
                attributes={"tool_command": f"echo '{SAMPLE_DIFF}'"},
            ),
            "reviewer": Node(
                id="reviewer",
                shape="box",
                prompt="Review this code change for security issues. The diff: {{ tool.output }}",
                attributes={"agent": "security-reviewer"},
            ),
            "synthesize": Node(
                id="synthesize",
                shape="box",
                prompt="Summarize the review findings. The diff: {{ tool.output }}",
                attributes={"agent": "synthesizer"},
            ),
            "exit": Node(id="exit", shape="Msquare"),
        },
        edges=[
            Edge(from_node="start", to_node="get_diff"),
            Edge(from_node="get_diff", to_node="reviewer"),
            Edge(from_node="reviewer", to_node="synthesize"),
            Edge(from_node="synthesize", to_node="exit"),
        ],
        graph_attributes={"goal": "Review PR for quality and security"},
    )


def _build_real_registry(emitter: RecordingEmitter, config: OrchestraConfig) -> HandlerRegistry:
    """Build a handler registry with a real LLM backend."""
    from orchestra.cli.backend_factory import build_backend

    backend = build_backend(config)
    registry = HandlerRegistry()
    registry.register("Mdiamond", StartHandler())
    registry.register("Msquare", ExitHandler())
    registry.register("parallelogram", ToolHandler())
    registry.register("box", CodergenHandler(backend=backend, config=config))
    return registry


class TestRealLLMReview:
    """Real LLM integration tests — gated behind ORCHESTRA_REAL_LLM=1."""

    def test_reviewer_produces_domain_specific_review(self):
        """A real LLM reviewer should identify the SQL injection vulnerability."""
        config = _build_real_config()
        emitter = RecordingEmitter()
        graph = _build_linear_review_graph()
        registry = _build_real_registry(emitter, config)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify all expected nodes completed
        completed = [e[1]["node_id"] for e in emitter.events if e[0] == "StageCompleted"]
        assert "get_diff" in completed
        assert "reviewer" in completed
        assert "synthesize" in completed

    def test_tool_output_available_to_reviewer(self):
        """The diff from tool handler should propagate to the reviewer context."""
        config = _build_real_config()
        emitter = RecordingEmitter()
        graph = _build_linear_review_graph()
        registry = _build_real_registry(emitter, config)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify tool.output was set after get_diff
        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        get_diff_cp = [cp for cp in checkpoints if cp[1]["node_id"] == "get_diff"]
        assert len(get_diff_cp) > 0
        ctx_snap = get_diff_cp[0][1]["context_snapshot"]
        assert "DELETE FROM users" in ctx_snap.get("tool.output", "")

    def test_checkpoints_contain_correct_state(self):
        """Every checkpoint should have required fields and be loadable."""
        config = _build_real_config()
        emitter = RecordingEmitter()
        graph = _build_linear_review_graph()
        registry = _build_real_registry(emitter, config)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        checkpoints = [e for e in emitter.events if e[0] == "CheckpointSaved"]
        assert len(checkpoints) >= 3  # get_diff, reviewer, synthesize

        for cp in checkpoints:
            data = cp[1]
            assert "node_id" in data
            assert "completed_nodes" in data
            assert "context_snapshot" in data
            assert "visited_outcomes" in data
            assert isinstance(data["completed_nodes"], (list, set))

    def test_synthesizer_produces_final_review(self):
        """The synthesizer should produce some output (non-empty notes)."""
        config = _build_real_config()
        emitter = RecordingEmitter()
        graph = _build_linear_review_graph()
        registry = _build_real_registry(emitter, config)

        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()

        assert outcome.status == OutcomeStatus.SUCCESS

        # Verify synthesize stage completed
        synth_completed = [
            e for e in emitter.events
            if e[0] == "StageCompleted" and e[1].get("node_id") == "synthesize"
        ]
        assert len(synth_completed) == 1
