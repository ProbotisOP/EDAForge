"""Content-addressed cache (section 12.2 and section 14).

Keys are SHA-256 digests of the canonical JSON of their parts (data hash, analyzer version,
parameters, seed, ...). Values are written atomically and carry a checksum that is verified on
every read; a corrupted entry is treated as a miss and removed.
"""

from __future__ import annotations

import contextlib
import json
import os
import tempfile
from pathlib import Path

from pydantic import JsonValue

from edaforge.canonical import canonical_bytes, content_hash, sha256_hex

__all__ = ["ContentCache"]

_HEADER_LEN = 64  # hex SHA-256


class ContentCache:
    """A directory-backed, content-addressed key/value store."""

    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def key(namespace: str, **parts: object) -> str:
        return content_hash({"namespace": namespace, "parts": parts})

    def _path(self, key: str) -> Path:
        if len(key) != _HEADER_LEN or any(c not in "0123456789abcdef" for c in key):
            msg = f"invalid cache key {key!r}"
            raise ValueError(msg)
        return self.root / key[:2] / key[2:]

    def contains(self, key: str) -> bool:
        return self.get_bytes(key) is not None

    def get_bytes(self, key: str) -> bytes | None:
        path = self._path(key)
        try:
            raw = path.read_bytes()
        except FileNotFoundError:
            return None
        checksum, sep, payload = raw[:_HEADER_LEN], raw[_HEADER_LEN : _HEADER_LEN + 1], raw[65:]
        if sep != b"\n" or checksum.decode("ascii", errors="replace") != sha256_hex(payload):
            with contextlib.suppress(FileNotFoundError):
                path.unlink()
            return None
        return payload

    def put_bytes(self, key: str, payload: bytes) -> None:
        path = self._path(key)
        path.parent.mkdir(parents=True, exist_ok=True)
        blob = sha256_hex(payload).encode("ascii") + b"\n" + payload
        fd, tmp_name = tempfile.mkstemp(dir=path.parent, prefix=".tmp-")
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(blob)
            os.replace(tmp_name, path)
        except BaseException:
            with contextlib.suppress(FileNotFoundError):
                Path(tmp_name).unlink()
            raise

    def get_json(self, key: str) -> JsonValue | None:
        payload = self.get_bytes(key)
        if payload is None:
            return None
        value: JsonValue = json.loads(payload)
        return value

    def put_json(self, key: str, value: object) -> None:
        self.put_bytes(key, canonical_bytes(value))
