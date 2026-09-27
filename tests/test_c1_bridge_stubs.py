"""Shared stubs for the C1 focused guard tests."""

from nexus_connector_core.native.adapter_types import (
    HarnessCapabilities, HarnessSession,
)


def harness_session(kind: str = "codex") -> HarnessSession:
    return HarnessSession(
        "native-session", kind, "agent", "STARTING",
        HarnessCapabilities(False, "IMMEDIATE", False, False, True),
        "2026-09-26T00:00:00Z")
