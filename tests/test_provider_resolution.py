from orchestra.config.providers import get_provider_settings, resolve_model, resolve_provider
from orchestra.config.settings import ProviderConfig, ProvidersConfig


def _make_config() -> ProvidersConfig:
    return ProvidersConfig(
        default="anthropic",
        anthropic=ProviderConfig(
            models={
                "smart": "claude-opus-4-20250514",
                "worker": "claude-sonnet-4-20250514",
                "cheap": "claude-haiku-3-20250514",
            },
            settings={"max_tokens": 4096},
        ),
        openai=ProviderConfig(
            models={
                "smart": "gpt-4o",
                "worker": "gpt-4o-mini",
                "cheap": "gpt-4o-mini",
            },
            settings={"api_base": "https://api.openai.com"},
        ),
    )


class TestResolveModel:
    def test_alias_resolution(self):
        config = _make_config()
        assert resolve_model("smart", "anthropic", config) == "claude-opus-4-20250514"

    def test_worker_alias(self):
        config = _make_config()
        assert resolve_model("worker", "anthropic", config) == "claude-sonnet-4-20250514"

    def test_literal_passthrough(self):
        config = _make_config()
        assert resolve_model("gpt-4o", "anthropic", config) == "gpt-4o"

    def test_unknown_alias_passthrough(self):
        config = _make_config()
        assert resolve_model("custom-model-v2", "anthropic", config) == "custom-model-v2"

    def test_openai_alias(self):
        config = _make_config()
        assert resolve_model("smart", "openai", config) == "gpt-4o"

    def test_unknown_provider_passthrough(self):
        config = _make_config()
        assert resolve_model("smart", "unknown_provider", config) == "smart"


class TestResolveProvider:
    def test_provider_default(self):
        config = _make_config()
        assert resolve_provider("", config) == "anthropic"

    def test_explicit_provider(self):
        config = _make_config()
        assert resolve_provider("openai", config) == "openai"

    def test_no_default_returns_empty(self):
        config = ProvidersConfig()
        assert resolve_provider("", config) == ""


class TestProviderSettings:
    def test_provider_specific_config(self):
        config = _make_config()
        settings = get_provider_settings("anthropic", config)
        assert settings["max_tokens"] == 4096

    def test_openai_settings(self):
        config = _make_config()
        settings = get_provider_settings("openai", config)
        assert settings["api_base"] == "https://api.openai.com"

    def test_unknown_provider_empty_settings(self):
        config = _make_config()
        settings = get_provider_settings("unknown_provider", config)
        assert settings == {}
