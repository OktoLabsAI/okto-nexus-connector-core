"""Tiny local LF peer used only for owned-spawn/write crash qualification."""

from __future__ import annotations

import os
import sys
import time


def main(marker: str) -> None:
    print(f"READY {os.getpid()}", flush=True)
    command = sys.stdin.buffer.readline()
    if command == b'{"cmd":"go"}\n':
        descriptor = os.open(marker, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        try:
            os.write(descriptor, b"native-peer-command-once")
            os.fsync(descriptor)
        finally:
            os.close(descriptor)
        print("ACK", flush=True)
    time.sleep(60)


if __name__ == "__main__":
    main(sys.argv[1])
