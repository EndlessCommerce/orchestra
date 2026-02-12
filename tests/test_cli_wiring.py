from orchestra.backends.cli_agent import CLIAgentBackend
from orchestra.backends.direct_llm import DirectLLMBackend
from orchestra.backends.langgraph_backend import LangGraphBackend
from orchestra.backends.simulation import SimulationBackend
from orchestra.config.settings import OrchestraConfig, ProviderConfig, ProvidersConfig
from orchestra.cli.backend_factory import build_backend as _build_backend


class TestBuildBackend:
    def test_default_simulation(self):
        config = OrchestraConfig()
        backend = _build_backend(config)
        assert isinstance(backend, SimulationBackend)

    def test_explicit_simulation(self):
        config = OrchestraConfig(backend="simulation")
        backend = _build_backend(config)
        assert isinstance(backend, SimulationBackend)

    def test_direct_backend(self):
        config = OrchestraConfig(
            backend="direct",
            providers=ProvidersConfig(
                default="anthropic",
                anthropic=ProviderConfig(models={"smart": "claude-opus-4-20250514"}),
            ),
        )
        backend = _build_backend(config)
        assert isinstance(backend, DirectLLMBackend)

    def test_langgraph_backend(self):
        config = OrchestraConfig(
            backend="langgraph",
            providers=ProvidersConfig(
                default="anthropic",
                anthropic=ProviderConfig(models={"smart": "claude-opus-4-20250514"}),
            ),
        )
        backend = _build_backend(config)
        assert isinstance(backend, LangGraphBackend)

    def test_cli_backend(self):
        config = OrchestraConfig(backend="cli")
        backend = _build_backend(config)
        assert isinstance(backend, CLIAgentBackend)
