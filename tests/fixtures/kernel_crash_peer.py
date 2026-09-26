"""Abrupt supervisor death at a kernel/native-effect admission boundary."""

from __future__ import annotations

import asyncio
import os
import sys
import time

from nexus_connector_core import ExecutionContext, Operation
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel


class FaultJournal(SQLiteJournal):
    def __init__(self, path: str, boundary: str):
        super().__init__(path)
        self.boundary = boundary

    async def mark_possible_effect(self, key):
        if self.boundary == "before_mark":
            os._exit(91)
        receipt = await super().mark_possible_effect(key)
        if self.boundary == "after_mark":
            os._exit(91)
        return receipt

    async def record_receipt(self, key, receipt):
        if self.boundary == "before_receipt":
            os._exit(91)
        result = await super().record_receipt(key, receipt)
        if self.boundary == "after_receipt":
            os._exit(91)
        return result


def context():
    return ExecutionContext("crash-server", "crash-executor", "binding",
                            "agent", "workspace", 1, 1, 7,
                            time.monotonic() + 60, frozenset({"turn.submit"}))


async def run(path: str, marker: str, boundary: str) -> None:
    journal = FaultJournal(path, boundary)
    kernel = OperationKernel(journal)
    operation = Operation("kernel-crash-operation", "crash-session",
                          "turn.submit", {"text": "synthetic"})

    async def effect():
        if boundary == "before_native":
            os._exit(91)
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, b"native-effect-once")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        if boundary == "after_native":
            os._exit(91)
        return "native-id"

    await kernel.execute(operation, context(), effect)


if __name__ == "__main__":
    asyncio.run(run(sys.argv[1], sys.argv[2], sys.argv[3]))
    os._exit(91)
