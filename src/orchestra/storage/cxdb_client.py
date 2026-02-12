from __future__ import annotations

from typing import Any
from urllib.parse import urlparse

import httpx

from orchestra.storage.binary_protocol import CxdbBinaryClient
from orchestra.storage.exceptions import CxdbConnectionError, CxdbError

# Re-export for backwards compatibility
__all__ = ["CxdbClient", "CxdbConnectionError", "CxdbError"]


class CxdbClient:
    """CXDB client using HTTP for reads/registry and binary protocol for writes."""

    def __init__(self, base_url: str = "http://localhost:9010") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=10.0)

        # Derive binary protocol host/port from HTTP URL
        parsed = urlparse(self._base_url)
        self._binary_host = parsed.hostname or "localhost"
        # Binary protocol runs on port 9009 (HTTP is 9010)
        http_port = parsed.port or 9010
        self._binary_port = http_port - 1  # 9010 -> 9009

        self._binary: CxdbBinaryClient | None = None

    def _get_binary(self) -> CxdbBinaryClient:
        if self._binary is None:
            self._binary = CxdbBinaryClient(
                host=self._binary_host, port=self._binary_port
            )
            self._binary.connect()
        return self._binary

    def health_check(self) -> dict[str, Any]:
        try:
            response = self._client.get("/healthz")
            response.raise_for_status()
            text = response.text.strip()
            if text == "ok":
                return {"status": "ok"}
            return response.json()
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(f"CXDB health check failed: {e}") from e

    def create_context(self, base_turn_id: str = "0") -> dict[str, Any]:
        return self._get_binary().create_context(int(base_turn_id))

    def append_turn(
        self,
        context_id: str,
        type_id: str,
        type_version: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return self._get_binary().append_turn(
            context_id=int(context_id),
            type_id=type_id,
            type_version=type_version,
            data=data,
        )

    def get_turns(
        self, context_id: str, limit: int = 64
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.get(
                f"/v1/contexts/{context_id}/turns",
                params={"limit": limit, "view": "typed"},
            )
            response.raise_for_status()
            body = response.json()
            # Response is {"meta": ..., "turns": [...]}
            raw_turns = body.get("turns", body) if isinstance(body, dict) else body
            if not isinstance(raw_turns, list):
                return []
            # Normalize: flatten declared_type.type_id into top-level type_id
            result = []
            for turn in raw_turns:
                if not isinstance(turn, dict):
                    continue
                normalized = dict(turn)
                declared = turn.get("declared_type", {})
                if declared:
                    normalized.setdefault("type_id", declared.get("type_id", ""))
                    normalized.setdefault("type_version", declared.get("type_version", 1))
                result.append(normalized)
            return result
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(
                f"Failed to get turns for context {context_id}: {e}"
            ) from e

    def list_contexts(
        self, limit: int = 100, offset: int = 0
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.get(
                "/v1/contexts",
                params={"limit": limit, "offset": offset},
            )
            response.raise_for_status()
            body = response.json()
            # Response is {"contexts": [...], ...}
            if isinstance(body, dict):
                return body.get("contexts", [])
            return body
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(f"Failed to list contexts: {e}") from e

    def publish_type_bundle(
        self, bundle_id: str, bundle: dict[str, Any]
    ) -> None:
        try:
            response = self._client.put(
                f"/v1/registry/bundles/{bundle_id}",
                json=bundle,
            )
            response.raise_for_status()
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(f"Failed to publish type bundle: {e}") from e

    def close(self) -> None:
        self._client.close()
        if self._binary is not None:
            self._binary.close()
