"""Availability projection against the PUBLIC API (C10/Z01).

Runnable example for both consumers:

* Nexus Server (embedded Core): evaluate its own host's inventory and
  apply agent policy on top of the TECHNICAL states.
* Nexus Connector (remote Core): produce the projection of ITS host
  and transmit ``to_dict()`` to the Server through its own versioned
  API - the Server never re-derives build/platform/containment rules.

The scenario is synthetic (no spawn, no journal, no credentials): TWO
installations of the same family (one qualified+selected, one merely
found), an attach installation (registered, never qualified), and the
absence of any claude_stream installation. UI acceptance criteria for
the Server repository: every row renders state + reasons verbatim,
two rows of one family never collapse, attach never renders enabled,
NOT_PROBED never renders as ready, and display_name is never used as
an identity.

Run: python examples/availability_projection.py [--json]
"""

import argparse
import json
import sys

from nexus_connector_core import (
    InstallationCandidate, evaluate_runtime_availability,
)


def build_scenario() -> list[InstallationCandidate]:
    # Two builds of ONE family: found-but-unprobed (needs selection
    # AND a probe) and qualified+selected. Same display_name, two
    # distinct candidate_refs - never merged.
    return [
        InstallationCandidate(
            "codex_app_server", "/opt/codex-a/codex", "fp-codex-a",
            "trusted_root", "candidate"),
        InstallationCandidate(
            "codex_app_server", "/opt/codex-b/codex", "fp-codex-b",
            "explicit", "selected", version="0.157.0",
            architecture="x86_64", build_identity="id-codex-b"),
        # Attach is registered for completeness; on a covered platform
        # it still evaluates UNQUALIFIED - never READY by existing.
        InstallationCandidate(
            "claude_attach", "/opt/claude/claude", "fp-claude",
            "explicit", "selected", version="1.0",
            architecture="x86_64"),
    ]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true",
                        help="emit the remote projection (fixture for "
                             "Server UI tests)")
    args = parser.parse_args()

    report = evaluate_runtime_availability(build_scenario())
    if args.json:
        print(json.dumps(report.to_dict(), indent=2, sort_keys=True))
        return 0

    print(f"core {report.core_version} format {report.format_version} "
          f"platform {report.platform}")
    for row in report.availability:
        reasons = ", ".join(row.reasons) or "-"
        print(f"{row.adapter_id:18} {row.display_name:22} "
              f"{row.state:24} {reasons}")
        if row.state == "READY_FOR_RUNTIME":
            print("      (technical readiness only - the agent's "
                  "authorization stays in the Server)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
