import json
from unittest.mock import MagicMock, patch

import httpx
import pytest

from orchestra.storage.cxdb_client import CxdbClient, CxdbConnectionError, CxdbError

BASE_URL = "http://test:9010"


def _make_client(handler) -> CxdbClient:
    """Create a CxdbClient with a mock HTTP transport."""
    client = CxdbClient.__new__(CxdbClient)
    client._base_url = BASE_URL
    client._client = httpx.Client(
        transport=httpx.MockTransport(handler), base_url=BASE_URL
    )
    client._binary_host = "test"
    client._binary_port = 9009
    client._binary = None
    return client


def test_health_check() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/healthz"
        return httpx.Response(200, text="ok")

    result = _make_client(handler).health_check()
    assert result == {"status": "ok"}


def test_health_check_json() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"status": "ok", "version": "1.0"})

    result = _make_client(handler).health_check()
    assert result["status"] == "ok"


def test_create_context() -> None:
    """create_context delegates to binary client."""
    client = _make_client(lambda r: httpx.Response(200))
    mock_binary = MagicMock()
    mock_binary.create_context.return_value = {"context_id": 1, "head_turn_id": 1, "head_depth": 0}
    client._binary = mock_binary

    result = client.create_context()
    assert result["context_id"] == 1
    mock_binary.create_context.assert_called_once_with(0)


def test_append_turn() -> None:
    """append_turn delegates to binary client."""
    client = _make_client(lambda r: httpx.Response(200))
    mock_binary = MagicMock()
    mock_binary.append_turn.return_value = {"context_id": 42, "turn_id": 5, "depth": 1}
    client._binary = mock_binary

    result = client.append_turn(
        context_id="42",
        type_id="dev.orchestra.NodeExecution",
        type_version=1,
        data={1: "plan"},
    )
    assert result["turn_id"] == 5
    mock_binary.append_turn.assert_called_once_with(
        context_id=42,
        type_id="dev.orchestra.NodeExecution",
        type_version=1,
        data={1: "plan"},
    )


def test_get_turns() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/contexts/42/turns"
        assert request.url.params.get("limit") == "64"
        assert request.url.params.get("view") == "typed"
        return httpx.Response(200, json=[{"turn_id": "1"}, {"turn_id": "2"}])

    result = _make_client(handler).get_turns("42")
    assert len(result) == 2


def test_list_contexts() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/contexts"
        assert request.url.params.get("limit") == "100"
        return httpx.Response(200, json=[{"context_id": "1"}])

    result = _make_client(handler).list_contexts()
    assert len(result) == 1


def test_publish_type_bundle() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/v1/registry/bundles/dev.orchestra.v1"
        assert request.method == "PUT"
        body = json.loads(request.content)
        assert body["registry_version"] == 1
        return httpx.Response(200, json={})

    _make_client(handler).publish_type_bundle(
        "dev.orchestra.v1", {"registry_version": 1}
    )


def test_connection_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("Connection refused")

    with pytest.raises(CxdbConnectionError, match="Cannot connect"):
        _make_client(handler).health_check()


def test_http_error() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    with pytest.raises(CxdbError, match="health check failed"):
        _make_client(handler).health_check()
