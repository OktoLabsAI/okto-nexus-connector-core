"""Private channel for the transcript and editor of an already-owned Pi process."""

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
_MAX_INSERT_BYTES = 4 * 1024
_MAX_FRAME_BYTES = 16 * 1024 + 128
_EDITOR_KEYS = frozenset({"insert", "enter", "newline", "backspace", "delete", "left", "right", "up", "down", "home", "end",
                          "snapshot", "clear"})
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
        return _output(frame)


def _output(frame: dict) -> bytes:
    if frame.keys() != {"type", "bytes"} or frame["type"] != "output" or type(frame["bytes"]) is not str:
        raise CoreError("NATIVE_UNAVAILABLE", STAGE)
    try:
        data = b64decode(frame["bytes"], validate=True)
    except ValueError as exc:
        raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc
    if not 1 <= len(data) <= _MAX_OUTPUT_BYTES:
        raise CoreError("NATIVE_UNAVAILABLE", STAGE)
    return data


def _valid_text(value, limit: int) -> bool:
    return (isinstance(value, str) and 0 < len(value) <= limit
            and all(char in "\t\n" or " " <= char and not "\x7f" <= char <= "\x9f"
                    and not "\ud800" <= char <= "\udfff" for char in value)
            and len(value.encode("utf-8")) <= limit)


@dataclass(frozen=True, slots=True)
class PiEditorUpdate:
    sequence: int
    draft: str | None = field(repr=False)
    limit_reached: bool = False


class PiRendererEditor:
    """Edit a local draft. Only the host can admit a resulting message."""

    def __init__(self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter, *, verify=None):
        self._reader, self._writer = reader, writer
        self._verify = verify
        self._sequence = 0
        self._waiting: int | None = None
        self._allow_draft = False

    async def edit(self, key: str, *, text: str | None = None):
        if self._verify is not None:
            await self._verify()
        if (not isinstance(key, str) or key not in _EDITOR_KEYS or self._waiting is not None
                or (not _valid_text(text, _MAX_INSERT_BYTES) if key == "insert" else text is not None)
                or self._sequence >= 2**31 - 1):
            raise CoreError("VALIDATION_ERROR", STAGE)
        self._sequence += 1
        self._waiting = self._sequence
        self._allow_draft = key in ("enter", "snapshot")
        request = {"type": "key", "sequence": self._sequence, "key": key, "text": text}
        try:
            self._writer.write(json.dumps(request, ensure_ascii=False).encode("utf-8") + b"\n")
            async with asyncio.timeout(3):
                await self._writer.drain()
        except (OSError, TimeoutError) as exc:
            raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc

    async def read_event(self) -> bytes | PiEditorUpdate | None:
        while True:
            try:
                async with asyncio.timeout(1):
                    frame = await _read_frame(self._reader)
                break
            except TimeoutError:
                if self._verify is not None:
                    await self._verify()
        if self._verify is not None:
            await self._verify()
        if frame is None:
            return None
        if frame.get("type") == "output":
            return _output(frame)
        if (frame.keys() != {"type", "sequence", "draft", "limit_reached"} or frame["type"] != "edited"
                or type(frame["sequence"]) is not int or frame["sequence"] != self._waiting
                or type(frame["limit_reached"]) is not bool):
            raise CoreError("NATIVE_UNAVAILABLE", STAGE)
        draft = frame["draft"]
        if draft is not None:
            if type(draft) is not str or not self._allow_draft or frame["limit_reached"]:
                raise CoreError("NATIVE_UNAVAILABLE", STAGE)
            try:
                draft = b64decode(draft, validate=True).decode("utf-8")
            except (ValueError, UnicodeError) as exc:
                raise CoreError("NATIVE_UNAVAILABLE", STAGE) from exc
            if not _valid_text(draft, _MAX_OUTPUT_BYTES):
                raise CoreError("NATIVE_UNAVAILABLE", STAGE)
        self._waiting = None
        return PiEditorUpdate(frame["sequence"], draft, frame["limit_reached"])


@dataclass(frozen=True, slots=True)
class PiRendererEndpoint:
    port: int
    session_id: str
    _key: str = field(repr=False)

    @asynccontextmanager
    async def attach(self, columns: int, rows: int, *, edit: bool = False, verify=None):
        if (type(columns) is not int or not 24 <= columns <= 300 or type(rows) is not int
                or not 8 <= rows <= 120 or type(edit) is not bool):
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
                        if edit:
                            kind += ".edit"
                        return hmac.digest(self._key.encode("ascii"), f"{kind}\n{fields}".encode("ascii"), "sha256").hex()

                    request = {"type": "attach", "revision": 2 if edit else 1, "session_id": self.session_id,
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
            yield PiRendererEditor(reader, writer, verify=verify) if edit else PiRendererReader(reader)
        finally:
            if writer is not None:
                writer.close()
