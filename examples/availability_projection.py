"""Availability projection + installation selection (C10/C11).

Reference flow for BOTH consumers against the public API - no private
imports, no spawn, no credentials:

  catalog -> discovery -> availability -> projection -> selection ->
  local resolution -> existing composition/prepare

The scenario is REAL discovery (not invented strings): two trusted
directories, each holding a byte-identical copy of a lab executable -
the A11-01 case. The two installations share ONE build identity but
have DISTINCT installation refs, so the projection distinguishes them
and the selected ref resolves back to EXACTLY one local candidate,
which feeds the existing composition (``create_runtime(candidates=..)``
/ ``prepare`` - prepare revalidates the target before any effect).

* Nexus Server (embedded Core): runs this on ITS host, applies agent
  policy on top of the TECHNICAL states, publishes options to the UI.
* Nexus Connector (remote Core): runs this on ITS host and transmits
  ``report.to_dict()`` (format 2, JSON-safe) to the Server through its
  own versioned API; the Server renders that executor's snapshot and
  returns the selected (executor_id, adapter_id, installation_ref) to
  the SAME host - executor scoping, inventory revision and TTL are
  validated by the hosts' envelope, never by the Core.

UI acceptance criteria (Server repo): every row renders state+reasons;
same-family rows never collapse by display_name/build; ``label``
differentiates copies but is never a key; NOT_PROBED never renders
ready; an unknown projection format version renders INCOMPATIBLE (the
Core's ``AvailabilityReport.from_dict`` refuses it typed).

Run: python examples/availability_projection.py [--select A|B] [--json]
"""

import argparse
import asyncio
import json
import os
import sys
import tempfile
from pathlib import Path

from nexus_connector_core import (
    DiscoveryRequest, LocalRuntimeCore, ShutdownPolicy,
    evaluate_runtime_availability, get_runtime_catalog,
    resolve_installation,
)
from nexus_connector_core.journal import SQLiteJournal

_LAB_BINARY = b"#!/bin/sh\n# nexus lab binary (never executed)\n"


class _NoOpenFactory:
    """This example never opens a session (no spawn, no provider)."""

    async def open(self, *args, **kwargs):
        raise RuntimeError("example: open is out of scope")


def _binary_name(name: str) -> str:
    return name + (".exe" if os.name == "nt" else "")


def _scenario_roots(base: Path):
    """Two trusted roots with byte-identical copies (distinct targets)."""
    roots = []
    for tag in ("A", "B"):
        root = base / f"install-{tag}" / "bin"
        root.mkdir(parents=True)
        binary = root / _binary_name("codex")
        binary.write_bytes(_LAB_BINARY)
        binary.chmod(0o755)  # POSIX: candidates must be executable
        roots.append(root)
    return tuple(roots)


async def _main(select: str, as_json: bool) -> int:
    base = Path(tempfile.mkdtemp(prefix="nexus-availability-"))
    roots = _scenario_roots(base)
    index = "AB".index(select.upper())
    # Process-local PATH so the public discovery finds the two copies
    # (the hosts do the same with their real installation roots).
    os.environ["PATH"] = os.pathsep.join(str(root) for root in roots) \
        + os.pathsep + os.environ.get("PATH", "")

    catalog = get_runtime_catalog()
    journal = SQLiteJournal(base / "journal.db")
    runtime = LocalRuntimeCore(
        journal, _NoOpenFactory(), candidates={},
        workspace_roots={"ws": str(base)},
        trusted_discovery_roots=tuple(str(root) for root in roots))
    try:
        inventory = await runtime.discover(
            DiscoveryRequest(("codex_app_server",)))
        report = evaluate_runtime_availability(inventory)

        rows = [row for row in report.availability
                if row.adapter_id == "codex_app_server"]
        if len(rows) != 2 or len({row.candidate_ref
                                  for row in rows}) != 2:
            raise RuntimeError("scenario broken: the two byte-identical "
                               "installations must project distinctly")
        chosen = rows[index]

        if as_json:
            payload = report.to_dict()
            payload["selected_installation"] = {
                "adapter_id": chosen.adapter_id,
                "candidate_ref": chosen.candidate_ref,
                "state": chosen.state,
            }
            print(json.dumps(payload, indent=2, sort_keys=True))
            return 0

        print(f"catalog: {len(catalog.runtimes)} runtime types; "
              f"projection format {report.format_version} on "
              f"{report.platform}")
        for row in rows:
            marker = "*" if row is chosen else " "
            print(f"{marker} {row.label:28} {row.state:12} "
                  f"ref=...{row.candidate_ref[-12:]}")
        print("  (same build bytes, TWO installations; labels "
              "differentiate copies - never keys)")

        # The selection resolves on the SAME host inventory to EXACTLY
        # one physical candidate; paths stay on the host.
        resolved = resolve_installation(
            inventory, "codex_app_server", chosen.candidate_ref)
        exact = (resolved.executable.lower() ==
                 str(roots[index] / _binary_name("codex")).lower())
        print(f"selected {select.upper()} -> resolved "
              f"{'EXACT target' if exact else 'MISMATCH'}")

        # The resolved candidate feeds the EXISTING composition path
        # (create_runtime(candidates=...) / prepare) - shown here by
        # composing with it; prepare revalidates before any effect.
        composing = LocalRuntimeCore(
            journal, _NoOpenFactory(),
            candidates={"codex_app_server": resolved},
            workspace_roots={"ws": str(base)})
        await composing.shutdown(ShutdownPolicy())
        print("composed runtime accepted the resolved installation "
              "(prepare/open revalidate before any effect)")
        return 0
    finally:
        await runtime.shutdown(ShutdownPolicy())
        journal.close()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--select", default="A", choices=["A", "B"])
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()
    return asyncio.run(_main(args.select, args.json))


if __name__ == "__main__":
    sys.exit(main())
