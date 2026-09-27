"""RC-11-09 owner: owned tree + journal, then block until session death."""
import asyncio
import os
import sys

sys.path.insert(0, "/mnt/d/projetos/Techridy/okto-nexus-connector-core/src")

from nexus_connector_core import OperationKey  # noqa: E402
from nexus_connector_core.journal import SQLiteJournal  # noqa: E402
from nexus_connector_core.native.process import (  # noqa: E402
    spawn_owned_process,
)

CHILD = (
    "import subprocess, sys, time\n"
    "subprocess.Popen([sys.executable, '-c', "
    "'import time; time.sleep(100000)'])\n"
    "subprocess.Popen([sys.executable, '-c', "
    "'import time; time.sleep(100000)'])\n"
    "marker = open('/var/tmp/rc1109-tree.stamp', 'w')\n"
    "marker.write(str(os.getpid()) if False else 'tree')\n"
    "marker.close()\n"
    "import os\n"
    "while True:\n"
    "    time.sleep(1)\n"
)


async def main() -> None:
    journal = SQLiteJournal("/var/tmp/rc1109-journal.db")
    await journal.admit(
        OperationKey("srv", "exe", "rc1109-op"),
        "sha256:" + "1" * 64, "rc1109-session", effect_imminent=True)
    env = {
        "PATH": os.environ.get("PATH", "/usr/bin:/bin"),
        "HOME": "/root",
        "LANG": "C.UTF-8",
    }
    proc = spawn_owned_process(
        [sys.executable, "-c", CHILD], cwd="/var/tmp", env=env)
    print(f"READY {proc.pid}", flush=True)
    await asyncio.sleep(100000)


asyncio.run(main())
