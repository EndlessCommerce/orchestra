"""CXDB binary protocol client for write operations (create context, append turn).

The CXDB HTTP API is read-only. Write operations use a binary protocol over TCP
on port 9009. This module implements the minimum protocol surface needed by Orchestra.

Protocol reference: CXDB Go client at clients/go/client.go
Frame format: 16-byte header (payload_len:u32, msg_type:u16, flags:u16, req_id:u64) + payload
"""

from __future__ import annotations

import socket
import struct
import threading
from typing import Any

import blake3
import msgpack

from orchestra.storage.exceptions import CxdbConnectionError, CxdbError

# Message type codes
MSG_HELLO = 1
MSG_CTX_CREATE = 2
MSG_APPEND_TURN = 5
MSG_ERROR = 255

# Header: payload_len(u32) + msg_type(u16) + flags(u16) + req_id(u64) = 16 bytes
HEADER_FMT = "<IHHQ"
HEADER_SIZE = struct.calcsize(HEADER_FMT)

# Encoding constants
ENCODING_MSGPACK = 1
COMPRESSION_NONE = 0


class CxdbBinaryClient:
    """TCP client for CXDB binary protocol write operations."""

    def __init__(self, host: str = "localhost", port: int = 9009, timeout: float = 10.0) -> None:
        self._host = host
        self._port = port
        self._timeout = timeout
        self._sock: socket.socket | None = None
        self._req_counter = 0
        self._lock = threading.Lock()
        self._session_id: int | None = None

    def connect(self) -> None:
        try:
            self._sock = socket.create_connection((self._host, self._port), timeout=self._timeout)
        except (OSError, ConnectionError) as e:
            raise CxdbConnectionError(
                f"Cannot connect to CXDB binary protocol at {self._host}:{self._port}: {e}"
            ) from e
        self._handshake()

    def _next_req_id(self) -> int:
        self._req_counter += 1
        return self._req_counter

    def _send_frame(self, msg_type: int, payload: bytes, flags: int = 0) -> int:
        req_id = self._next_req_id()
        header = struct.pack(HEADER_FMT, len(payload), msg_type, flags, req_id)
        assert self._sock is not None
        self._sock.sendall(header + payload)
        return req_id

    def _recv_exactly(self, n: int) -> bytes:
        assert self._sock is not None
        buf = bytearray()
        while len(buf) < n:
            chunk = self._sock.recv(n - len(buf))
            if not chunk:
                raise CxdbConnectionError("Connection closed by CXDB server")
            buf.extend(chunk)
        return bytes(buf)

    def _recv_frame(self) -> tuple[int, int, int, bytes]:
        """Receive a frame. Returns (msg_type, flags, req_id, payload)."""
        header = self._recv_exactly(HEADER_SIZE)
        payload_len, msg_type, flags, req_id = struct.unpack(HEADER_FMT, header)
        payload = self._recv_exactly(payload_len) if payload_len > 0 else b""
        return msg_type, flags, req_id, payload

    def _handshake(self) -> None:
        client_tag = "orchestra-v0.1"
        tag_bytes = client_tag.encode("utf-8")
        # protocol_version(u16) + tag_len(u16) + tag + meta_len(u32, 0 = no metadata)
        payload = struct.pack("<HH", 1, len(tag_bytes)) + tag_bytes + struct.pack("<I", 0)
        self._send_frame(MSG_HELLO, payload)

        msg_type, _flags, _req_id, resp = self._recv_frame()
        if msg_type == MSG_ERROR:
            self._raise_error(resp)
        if msg_type != MSG_HELLO:
            raise CxdbError(f"Expected HELLO response, got msg_type={msg_type}")

        self._session_id = struct.unpack_from("<Q", resp, 0)[0]

    def create_context(self, base_turn_id: int = 0) -> dict[str, Any]:
        with self._lock:
            if self._sock is None:
                self.connect()

            payload = struct.pack("<Q", base_turn_id)
            self._send_frame(MSG_CTX_CREATE, payload)

            msg_type, _flags, _req_id, resp = self._recv_frame()
            if msg_type == MSG_ERROR:
                self._raise_error(resp)
            if msg_type != MSG_CTX_CREATE:
                raise CxdbError(f"Expected CTX_CREATE response, got msg_type={msg_type}")

            context_id, head_turn_id, head_depth = struct.unpack_from("<QQI", resp, 0)
            return {
                "context_id": context_id,
                "head_turn_id": head_turn_id,
                "head_depth": head_depth,
            }

    def append_turn(
        self,
        context_id: int,
        type_id: str,
        type_version: int,
        data: dict[str, Any],
        parent_turn_id: int = 0,
    ) -> dict[str, Any]:
        with self._lock:
            if self._sock is None:
                self.connect()

            # Encode data as msgpack
            payload_bytes = msgpack.packb(data, use_bin_type=True)
            content_hash = blake3.blake3(payload_bytes).digest()
            type_id_bytes = type_id.encode("utf-8")

            buf = struct.pack("<QQ", context_id, parent_turn_id)
            buf += struct.pack("<I", len(type_id_bytes)) + type_id_bytes
            buf += struct.pack("<I", type_version)
            buf += struct.pack("<III", ENCODING_MSGPACK, COMPRESSION_NONE, len(payload_bytes))
            buf += content_hash  # 32 bytes BLAKE3
            buf += struct.pack("<I", len(payload_bytes)) + payload_bytes
            buf += struct.pack("<I", 0)  # no idempotency key

            self._send_frame(MSG_APPEND_TURN, buf)

            msg_type, _flags, _req_id, resp = self._recv_frame()
            if msg_type == MSG_ERROR:
                self._raise_error(resp)
            if msg_type != MSG_APPEND_TURN:
                raise CxdbError(f"Expected APPEND_TURN response, got msg_type={msg_type}")

            ctx_id, new_turn_id, new_depth = struct.unpack_from("<QQI", resp, 0)
            return {
                "context_id": ctx_id,
                "turn_id": new_turn_id,
                "depth": new_depth,
            }

    def _raise_error(self, payload: bytes) -> None:
        if len(payload) >= 8:
            code = struct.unpack_from("<I", payload, 0)[0]
            detail_len = struct.unpack_from("<I", payload, 4)[0]
            detail = payload[8 : 8 + detail_len].decode("utf-8", errors="replace")
            raise CxdbError(f"CXDB error {code}: {detail}")
        raise CxdbError(f"CXDB error (raw): {payload!r}")

    def close(self) -> None:
        if self._sock is not None:
            try:
                self._sock.close()
            except OSError:
                pass
            self._sock = None
