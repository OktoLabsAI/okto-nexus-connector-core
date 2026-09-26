"""No-turn RPC handshake of an explicitly selected installed Pi release.

Uses a disposable Pi configuration directory, no session, no tools/resources,
and offline mode. It sends only get_state, never a model prompt.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import tempfile
from pathlib import Path


def _digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("node", type=Path)
    parser.add_argument("cli", type=Path)
    args = parser.parse_args()
    node = args.node.resolve(strict=True)
    cli = args.cli.resolve(strict=True)
    if not node.is_file() or not cli.is_file() or cli.suffix != ".js":
        raise SystemExit("expected an explicit node executable and Pi CLI JavaScript file")
    before = (_digest(node), _digest(cli))
    version = subprocess.run(
        [str(node), str(cli), "--version"], cwd=str(Path.cwd()),
        capture_output=True, text=True, timeout=8, check=True,
    ).stdout.strip()
    if not version or len(version) > 64 or any(
            character not in "0123456789." for character in version):
        raise SystemExit("Pi returned an invalid version")
    with tempfile.TemporaryDirectory(prefix="nexus-core-pi-probe-") as directory:
        environment = {name: value for name, value in os.environ.items()
                       if name.upper() in {"PATH", "SYSTEMROOT", "WINDIR", "COMSPEC",
                                            "TEMP", "TMP", "LOCALAPPDATA", "APPDATA"}}
        environment["PI_CODING_AGENT_DIR"] = directory
        environment["PI_OFFLINE"] = "1"
        process = subprocess.Popen(
            [str(node), str(cli), "--mode", "rpc", "--no-session",
             "--no-tools", "--no-extensions", "--no-skills",
             "--no-prompt-templates", "--no-themes", "--no-context-files",
             "--no-approve", "--offline"],
            cwd=str(Path.cwd()), env=environment,
            stdin=subprocess.PIPE, stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        try:
            stdout, _ = process.communicate(
                input=b'{"id":"core-probe-1","type":"get_state"}\n',
                timeout=12,
            )
        except subprocess.TimeoutExpired:
            process.kill()
            process.communicate(timeout=3)
            raise SystemExit("Pi RPC get_state timed out") from None
    if (_digest(node), _digest(cli)) != before:
        raise SystemExit("selected Node/Pi files changed during probe")
    records = []
    for line in stdout.splitlines():
        if len(line) > 1024 * 1024:
            raise SystemExit("Pi RPC record exceeded probe limit")
        records.append(json.loads(line))
    replies = [record for record in records
               if record.get("type") == "response" and
               record.get("command") == "get_state"]
    if len(replies) != 1 or replies[0].get("success") is not True:
        raise SystemExit("Pi RPC did not return one successful get_state response")
    print(json.dumps({
        "version": version,
        "node_sha256": before[0],
        "cli_sha256": before[1],
        "exit_code": process.returncode,
        "get_state_id_echo": replies[0].get("id") == "core-probe-1",
        "get_state_data_object": isinstance(replies[0].get("data"), dict),
        "response_count": len(replies),
        "other_record_types": sorted({str(record.get("type")) for record in records
                                      if record.get("type") != "response"}),
        "model_request_sent": False,
    }, sort_keys=True))


if __name__ == "__main__":
    main()
