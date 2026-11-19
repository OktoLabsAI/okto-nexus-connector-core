"""An independent, read-only text view of an existing Claude pseudoconsole."""

import asyncio
import codecs

from ..models import CoreError

_LIMIT = 16 * 1024


class _TerminalText:
    def __init__(self):
        self._state = ""
        self._string = ""

    def read(self, text):
        result = []
        for char in text:
            if self._state == "string":
                if char == "\x9c" or (char == "\x07" and self._string == "osc"):
                    self._state = ""
                elif char == "\x1b":
                    self._state = "string_escape"
            elif self._state == "string_escape":
                self._state = "" if char == "\\" else "string"
            elif char in ("\x1b", "\x9b"):
                self._state = "escape" if char == "\x1b" else "csi"
            elif self._state == "escape":
                if char in "]PX^_":
                    self._state = "string"
                    self._string = "osc" if char == "]" else "other"
                elif char == "[":
                    self._state = "csi"
                elif " " <= char <= "/":
                    self._state = "escape"
                else:
                    self._state = ""
            elif self._state == "csi":
                if "@" <= char <= "~":
                    self._state = ""
            elif char in ("\x90", "\x98", "\x9d", "\x9e", "\x9f"):
                self._state = "string"
                self._string = "osc" if char == "\x9d" else "other"
            elif char in "\r\n\t" or (" " <= char and not "\x7f" <= char <= "\x9f"):
                result.append(char)
        return "".join(result)


class ClaudeTerminalReader:
    def __init__(self, terminal, redactor):
        self._read = terminal.read_output
        self._redactor = redactor
        self._cursor = 0
        self._decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        self._text = _TerminalText()
        self._pending = ""
        self._idle_flushed = False

    async def read_output(self):
        """Read another chunk without writing to or disposing the owner."""
        try:
            frame = await asyncio.to_thread(self._read, self._cursor, timeout=0.25)
        except TimeoutError:
            if self._idle_flushed or not self._pending:
                raise
            self._idle_flushed = True
            output, self._pending = self._redactor.release_text_tail(self._pending)
            return output.encode("utf-8")
        if frame is None:
            return None
        self._idle_flushed = False
        self._cursor = frame.sequence
        text = self._text.read(self._decoder.decode(frame.data))
        output, self._pending = self._redactor._split(self._pending + text, final=False)
        if len(self._pending) > _LIMIT:
            raise CoreError("CAPACITY_EXCEEDED", "claude_terminal_read")
        return output.encode("utf-8")
