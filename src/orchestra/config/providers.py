from __future__ import annotations

from typing import Any

from orchestra.config.settings import ProvidersConfig


def resolve_model(
    alias: str,
    provider_name: str,
    providers_config: ProvidersConfig,
) -> str:
    provider = _get_provider_config(provider_name, providers_config)
    if provider is not None and alias in provider.models:
        return provider.models[alias]
    return alias


def resolve_provider(
    provider_name: str,
    providers_config: ProvidersConfig,
) -> str:
    if provider_name:
        return provider_name
    return providers_config.default


def get_provider_settings(
    provider_name: str,
    providers_config: ProvidersConfig,
) -> dict[str, Any]:
    provider = _get_provider_config(provider_name, providers_config)
    if provider is not None:
        return dict(provider.settings)
    return {}


def _get_provider_config(provider_name: str, providers_config: ProvidersConfig):
    return getattr(providers_config, provider_name, None)
