import asyncio
import subprocess
import sys
import time
from pathlib import Path

import pytest

from nexus_connector_core import ExecutionContext, Operation, OperationKey
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.kernel import OperationKernel


PEER = Path(__file__).parent / "fixtures" / "kernel_crash_peer.py"
KEY = OperationKey("crash-server", "crash-executor", "kernel-crash-operation")
OPERATION = Operation("kernel-crash-operation", "crash-session",
                      "turn.submit", {"text": "synthetic"})


def _context():
    return ExecutionContext("crash-server", "crash-executor", "binding",
                            "agent", "workspace", 1, 1, 7,
                            time.monotonic() + 60, frozenset({"turn.submit"}))


@pytest.mark.parametrize("boundary,stage,marker_exists", [
    ("before_mark", "RECEIVED_DURABLE", False),
    ("after_mark", "SUBMISSION_STARTED", False),
    ("before_native", "SUBMISSION_STARTED", False),
    ("after_native", "SUBMISSION_STARTED", True),
    ("before_receipt", "SUBMISSION_STARTED", True),
    ("after_receipt", "SUBMITTED", True),
])
def test_abrupt_kernel_death_never_replays_same_intent(
        tmp_path, boundary, stage, marker_exists):
    path = tmp_path / f"{boundary}.db"
    marker = tmp_path / f"{boundary}.effect"
    child = subprocess.run([sys.executable, str(PEER), str(path),
                            str(marker), boundary], capture_output=True,
                           text=True, timeout=20)
    assert child.returncode == 91, child.stderr
    assert marker.exists() == marker_exists
    if marker_exists:
        assert marker.read_bytes() == b"native-effect-once"

    async def inspect():
        journal = SQLiteJournal(path)
        try:
            receipt = await journal.get_receipt(KEY)
            assert receipt is not None and receipt.stage == stage
            if stage == "RECEIVED_DURABLE":
                assert not receipt.possible_effect and receipt.retry_safe
            else:
                assert receipt.possible_effect and not receipt.retry_safe
            invoked = False

            async def forbidden_effect():
                nonlocal invoked
                invoked = True
                raise AssertionError("effect replayed")

            replay = await OperationKernel(journal).execute(
                OPERATION, _context(), forbidden_effect)
            assert replay == receipt
            assert not invoked
        finally:
            journal.close()

    asyncio.run(inspect())
