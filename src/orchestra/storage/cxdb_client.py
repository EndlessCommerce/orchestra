from __future__ import annotations

from typing import Any

import httpx


class CxdbError(Exception):
    pass


class CxdbConnectionError(CxdbError):
    pass


class CxdbClient:
    def __init__(self, base_url: str = "http://localhost:9010") -> None:
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(base_url=self._base_url, timeout=10.0)

    def health_check(self) -> dict[str, Any]:
        try:
            response = self._client.get("/health")
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(f"CXDB health check failed: {e}") from e

    def create_context(self, base_turn_id: str = "0") -> dict[str, Any]:
        try:
            response = self._client.post(
                "/v1/contexts/create",
                json={"base_turn_id": base_turn_id},
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(f"Failed to create context: {e}") from e

    def append_turn(
        self,
        context_id: str,
        type_id: str,
        type_version: int,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        try:
            response = self._client.post(
                f"/v1/contexts/{context_id}/append",
                json={
                    "type_id": type_id,
                    "type_version": type_version,
                    "data": data,
                },
            )
            response.raise_for_status()
            return response.json()
        except httpx.ConnectError as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB at {self._base_url}: {e}"
            ) from e
        except httpx.HTTPStatusError as e:
            raise CxdbError(
                f"Failed to append turn to context {context_id}: {e}"
            ) from e

    def get_turns(
        self, context_id: str, limit: int = 64
    ) -> list[dict[str, Any]]:
        try:
            response = self._client.get(
                f"/v1/contexts/{context_id}/turns",
                params={"limit": limit, "view": "typed"},
            )
            response.raise_for_status()
            return response.json()
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
            return response.json()
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
