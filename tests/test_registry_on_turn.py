from unittest.mock import MagicMock

from orchestra.handlers.codergen_handler import CodergenHandler
from orchestra.handlers.registry import default_registry


class TestRegistryOnTurn:
    def test_on_turn_passed_to_codergen_handler(self) -> None:
        mock_backend = MagicMock()
        mock_on_turn = MagicMock()
        registry = default_registry(backend=mock_backend, on_turn=mock_on_turn)
        handler = registry.get("box")
        assert isinstance(handler, CodergenHandler)
        assert handler._on_turn is mock_on_turn

    def test_on_turn_default_none(self) -> None:
        mock_backend = MagicMock()
        registry = default_registry(backend=mock_backend)
        handler = registry.get("box")
        assert isinstance(handler, CodergenHandler)
        assert handler._on_turn is None

    def test_existing_registrations_preserved(self) -> None:
        mock_backend = MagicMock()
        registry = default_registry(backend=mock_backend, on_turn=MagicMock())
        assert registry.get("Mdiamond") is not None
        assert registry.get("Msquare") is not None
        assert registry.get("box") is not None
        assert registry.get("diamond") is not None
