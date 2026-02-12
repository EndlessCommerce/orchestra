from pathlib import Path
from unittest.mock import MagicMock

import pytest

from orchestra.backends.direct_llm import DirectLLMBackend
from orchestra.backends.simulation import SimulationBackend
from orchestra.config.settings import (
    AgentConfig,
    OrchestraConfig,
    ProviderConfig,
    ProvidersConfig,
)
from orchestra.engine.runner import PipelineRunner
from orchestra.events.dispatcher import EventDispatcher
from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.registry import default_registry
from orchestra.models.context import Context
from orchestra.models.graph import Edge, Node, PipelineGraph
from orchestra.models.outcome import OutcomeStatus
from orchestra.transforms.model_stylesheet import apply_model_stylesheet


def _make_simple_graph(
    node_attrs: dict | None = None,
    graph_attrs: dict | None = None,
) -> PipelineGraph:
    attrs = node_attrs or {}
    g_attrs = graph_attrs or {}
    return PipelineGraph(
        name="test_pipeline",
        nodes={
            "start": Node(id="start", label="Start", shape="Mdiamond", attributes={}),
            "work": Node(
                id="work",
                label="Work",
                shape="box",
                prompt="Do the work",
                attributes=attrs,
            ),
            "exit": Node(id="exit", label="Exit", shape="Msquare", attributes={}),
        },
        edges=[
            Edge(from_node="start", to_node="work", attributes={}),
            Edge(from_node="work", to_node="exit", attributes={}),
        ],
        graph_attributes={"goal": "test goal", **g_attrs},
    )


class _RecordingEmitter:
    def __init__(self):
        self.events: list[tuple[str, dict]] = []

    def emit(self, event_type: str, **data):
        self.events[event_type] = data  # type: ignore

    def __getattr__(self, name):
        if name == "events":
            return object.__getattribute__(self, "events")
        return lambda **kwargs: None


class TestPipelineWithAgentConfig:
    def test_agent_config_composes_prompt(self, tmp_path: Path):
        (tmp_path / "role.yaml").write_text("content: You are a coder.")
        (tmp_path / "task.yaml").write_text("content: Write code for the goal.")

        config = OrchestraConfig(
            agents={
                "coder": AgentConfig(
                    role=str(tmp_path / "role.yaml"),
                    task=str(tmp_path / "task.yaml"),
                )
            }
        )

        prompts_received: list[str] = []

        class CapturingBackend:
            def run(self, node, prompt, context, on_turn=None):
                prompts_received.append(prompt)
                return "Done"

        backend = CapturingBackend()
        handler = CodergenHandler(backend=backend, config=config)

        node = Node(id="work", label="Work", shape="box", prompt="default", attributes={"agent": "coder"})
        handler.handle(node, Context(), _make_simple_graph())

        assert len(prompts_received) == 1
        assert "You are a coder." in prompts_received[0]
        assert "Write code" in prompts_received[0]


class TestPipelineWithStylesheet:
    def test_stylesheet_assigns_models(self):
        graph = PipelineGraph(
            name="test",
            nodes={
                "start": Node(id="start", shape="Mdiamond", attributes={}),
                "code": Node(id="code", shape="box", attributes={"class": "coding"}),
                "review": Node(id="review", shape="box", attributes={"class": "review"}),
                "exit": Node(id="exit", shape="Msquare", attributes={}),
            },
            edges=[
                Edge(from_node="start", to_node="code", attributes={}),
                Edge(from_node="code", to_node="review", attributes={}),
                Edge(from_node="review", to_node="exit", attributes={}),
            ],
            graph_attributes={
                "goal": "test",
                "model_stylesheet": ".coding { llm_model: worker; }\n.review { llm_model: smart; }",
            },
        )

        graph = apply_model_stylesheet(graph)
        assert graph.nodes["code"].attributes["llm_model"] == "worker"
        assert graph.nodes["review"].attributes["llm_model"] == "smart"


class TestPipelineWithInlineAgent:
    def test_inline_agent_role(self, tmp_path: Path):
        role_path = tmp_path / "engineer.yaml"
        role_path.write_text("content: You are a software engineer.")

        config = OrchestraConfig(
            agents={
                "engineer": AgentConfig(role=str(role_path))
            }
        )

        prompts_received: list[str] = []

        class CapturingBackend:
            def run(self, node, prompt, context, on_turn=None):
                prompts_received.append(prompt)
                return "Done"

        handler = CodergenHandler(backend=CapturingBackend(), config=config)
        node = Node(id="n", shape="box", prompt="default", attributes={"agent": "engineer"})
        handler.handle(node, Context(), _make_simple_graph())
        assert "software engineer" in prompts_received[0]


class TestConfigValidation:
    def test_invalid_backend_type(self):
        from orchestra.config.settings import OrchestraConfig

        config = OrchestraConfig(backend="invalid_backend")
        assert config.backend == "invalid_backend"

    def test_missing_agent_reference(self):
        config = OrchestraConfig()
        handler = CodergenHandler(backend=SimulationBackend(), config=config)
        node = Node(id="n", shape="box", prompt="fallback", attributes={"agent": "nonexistent"})
        outcome = handler.handle(node, Context(), _make_simple_graph())
        assert outcome.status == OutcomeStatus.SUCCESS


class TestBackendSelection:
    def test_default_simulation(self):
        config = OrchestraConfig()
        registry = default_registry()
        handler = registry.get("box")
        assert handler is not None

    def test_with_custom_backend(self):
        class CustomBackend:
            def run(self, node, prompt, context, on_turn=None):
                return "custom"

        registry = default_registry(backend=CustomBackend())
        handler = registry.get("box")
        node = Node(id="n", shape="box", prompt="test", attributes={})
        outcome = handler.handle(node, Context(), _make_simple_graph())
        assert outcome.notes == "custom"


class TestProviderSwitching:
    def test_changing_default_provider(self):
        from orchestra.config.model_resolution import resolve_node_model

        anthropic_config = ProvidersConfig(
            default="anthropic",
            anthropic=ProviderConfig(models={"smart": "claude-opus-4-20250514"}),
            openai=ProviderConfig(models={"smart": "gpt-4o"}),
        )

        openai_config = ProvidersConfig(
            default="openai",
            anthropic=ProviderConfig(models={"smart": "claude-opus-4-20250514"}),
            openai=ProviderConfig(models={"smart": "gpt-4o"}),
        )

        node = Node(id="n", shape="box", attributes={})
        graph = PipelineGraph(
            name="test",
            nodes={},
            edges=[],
            graph_attributes={"llm_model": "smart"},
        )

        model_a, provider_a = resolve_node_model(node, None, graph, anthropic_config)
        assert model_a == "claude-opus-4-20250514"
        assert provider_a == "anthropic"

        model_o, provider_o = resolve_node_model(node, None, graph, openai_config)
        assert model_o == "gpt-4o"
        assert provider_o == "openai"


class TestEndToEndSimulatedPipeline:
    def test_full_pipeline_with_simulation_backend(self):
        graph = _make_simple_graph()
        emitter = EventDispatcher()
        registry = default_registry()
        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()
        assert outcome.status == OutcomeStatus.SUCCESS

    def test_full_pipeline_with_custom_backend(self):
        class EchoBackend:
            def run(self, node, prompt, context, on_turn=None):
                return f"Echo: {prompt}"

        graph = _make_simple_graph()
        emitter = EventDispatcher()
        registry = default_registry(backend=EchoBackend())
        runner = PipelineRunner(graph, registry, emitter)
        outcome = runner.run()
        assert outcome.status == OutcomeStatus.SUCCESS
