"""Private reader for the renderer inside an already-owned Pi process."""

from __future__ import annotations

import asyncio
from base64 import b64decode
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
import hmac
import json
import re

from ..models import CoreError
from ..protocol import strict_json


_HEX = re.compile(r"[0-9a-f]{64}\Z", re.ASCII)
_MAX_OUTPUT_BYTES = 12 * 1024
_MAX_FRAME_BYTES = 16 * 1024 + 128
STAGE = "pi_renderer"


async def _read_frame(reader: asyncio.StreamReader) -> dict | None:
    try:
        line = await reader.readline()
        if not line:
            return None
        if len(line) > _MAX_FRAME_BYTES or not line.endswith(b"\n"):
            raise ValueError("invalid frame size")
        frame = strict_json(line.decode("utf-8"))
        if not isinstance(frame, dict):
            raise ValueError("invalid frame")
        return frame
    except (OSError, ValueError, RecursionError) as exc:
        raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc


class PiRendererReader:
    def __init__(self, reader: asyncio.StreamReader):
        self._reader = reader

    async def read_output(self) -> bytes | None:
        frame = await _read_frame(self._reader)
        if frame is None:
            return None
        if frame.keys() != {"type", "bytes"} or frame["type"] != "output" or type(frame["bytes"]) is not str:
            raise CoreError("NATIVE_UNAVAILABLE", STAGE)
        try:
            data = b64decode(frame["bytes"], validate=True)
        except ValueError as exc:
            raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc
        if not 1 <= len(data) <= _MAX_OUTPUT_BYTES:
            raise CoreError("NATIVE_UNAVAILABLE", STAGE)
        return data


@dataclass(frozen=True, slots=True)
class PiRendererEndpoint:
    port: int
    session_id: str
    _key: str = field(repr=False)

    @asynccontextmanager
    async def attach(self, columns: int, rows: int):
        if type(columns) is not int or not 24 <= columns <= 300 or type(rows) is not int or not 8 <= rows <= 120:
            raise CoreError("VALIDATION_ERROR", STAGE)
        writer = None
        try:
            try:
                async with asyncio.timeout(3):
                    reader, writer = await asyncio.open_connection("127.0.0.1", self.port, limit=_MAX_FRAME_BYTES)
                    challenge = await _read_frame(reader)
                    if (not challenge or challenge.keys() != {"type", "revision", "challenge"}
                            or challenge["type"] != "challenge" or type(challenge["revision"]) is not int
                            or challenge["revision"] != 1 or type(challenge["challenge"]) is not str
                            or not _HEX.fullmatch(challenge["challenge"])):
                        raise CoreError("NATIVE_UNAVAILABLE", STAGE)
                    fields = f"{challenge['challenge']}\n{self.session_id}\n{columns}\n{rows}"

                    def proof(kind: str) -> str:
                        return hmac.digest(self._key.encode("ascii"), f"{kind}\n{fields}".encode("ascii"), "sha256").hex()

                    request = {"type": "attach", "revision": 1, "session_id": self.session_id,
                               "columns": columns, "rows": rows, "proof": proof("attach")}
                    writer.write(json.dumps(request).encode("ascii") + b"\n")
                    await writer.drain()
                    ready = await _read_frame(reader)
                    if (not ready or ready.keys() != {"type", "proof"} or ready["type"] != "ready"
                            or type(ready["proof"]) is not str or not _HEX.fullmatch(ready["proof"])
                            or not hmac.compare_digest(ready["proof"], proof("ready"))):
                        raise CoreError("NATIVE_UNAVAILABLE", STAGE)
            except (OSError, TimeoutError) as exc:
                raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc
            yield PiRendererReader(reader)
        finally:
            if writer is not None:
                writer.close()
