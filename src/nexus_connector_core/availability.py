"""Public per-candidate technical availability (C10/Z01, C9-01.4).

The C9 catalog answers "which adapter TYPES does this Core know".
This module answers the binding contract's remaining half: "which
CONCRETE installations on THIS host are technically ready - and why".

Design contract (mirrors the C10 plan):

* PASSIVE: the assessment reuses the Core's REAL policies - the
  registry's platform support, ``compatibility``'s exact-build
  qualification and the containment preflight. It never logs into a
  provider, never spawns, never opens a journal and never invents a
  second allowlist. An absent probe stays INCONCLUSIVE (``NOT_PROBED``)
  - never READY by omission.
* TYPED + PATH-FREE: one ``CandidateAvailability`` per candidate plus
  one ``NOT_INSTALLED`` row per discoverable catalog adapter without a
  candidate. ``candidate_ref`` is the inventory's own opaque content
  id (the discovery fingerprint); the EXECUTING host resolves it back
  to a concrete path at prepare time (which revalidates anyway).
  ``to_dict()`` is the explicit, versioned, JSON-safe remote
  projection - the NXL frames are untouched (documented decision: the
  Connector/Server transmit the projection through their own
  versioned API surface).
* TECHNICAL ONLY: ``READY_FOR_RUNTIME`` means "no technical blocker
  observed". It is NEVER the agent's authorization - canonical
  binding and permissions belong to the Nexus Server.

Evaluation order of blocking dimensions (most fundamental first):
platform implementation -> attach/qualification -> containment ->
preparation (trust/selection). EVERY applicable reason is reported in
``reasons`` as stable codes, whatever the headline state.
"""

from __future__ import annotations

import sys
from dataclasses import dataclass
from typing import Iterable

from .catalog import get_runtime_catalog
from .models import CoreError, InstallationCandidate, Inventory
from .native.adapters.compatibility import qualified_build
from .native.process.preflight import containment_preflight

#: Bumped when the projection's SHAPE changes.
AVAILABILITY_FORMAT_VERSION = 1

#: Technical states (the DISTINCTIONS are contract; the exact spellings
#: are stable public constants).
NOT_INSTALLED = "NOT_INSTALLED"
UNSUPPORTED_PLATFORM = "UNSUPPORTED_PLATFORM"
NOT_PROBED = "NOT_PROBED"
UNQUALIFIED_BUILD = "UNQUALIFIED_BUILD"
CONTAINMENT_UNAVAILABLE = "CONTAINMENT_UNAVAILABLE"
PREPARATION_REQUIRED = "PREPARATION_REQUIRED"
READY_FOR_RUNTIME = "READY_FOR_RUNTIME"

_BLOCKING_ORDER = (UNSUPPORTED_PLATFORM, UNQUALIFIED_BUILD,
                   NOT_PROBED, CONTAINMENT_UNAVAILABLE,
                   PREPARATION_REQUIRED)


@dataclass(frozen=True, slots=True)
class CandidateAvailability:
    """One concrete installation's technical assessment.

    ``candidate_ref`` is opaque and content-addressed (the producing
    host's inventory fingerprint). Two installations of the same build
    share it and stay TWO rows - the binding references
    executor + adapter + candidate/ref and the executing host resolves
    the concrete installation; display_name is never an identity.
    """

    adapter_id: str
    candidate_ref: str
    display_name: str
    connection_mode: str
    state: str
    reasons: tuple[str, ...]
    version: str | None
    architecture: str | None
    build_identity: str | None
    trust: str
    source: str
    #: "qualified" | "unqualified" | "not_probed"
    qualification: str
    #: "available" | "unavailable" | "unverified"
    containment: str


@dataclass(frozen=True, slots=True)
class AvailabilityReport:
    """Versioned projection for consumers (local or remote)."""

    core_version: str
    format_version: int
    #: The EXECUTION host's platform - not the rendering UI's.
    platform: str
    availability: tuple[CandidateAvailability, ...]

    def to_dict(self) -> dict:
        """Explicit JSON-safe remote projection (no paths, no modules,
        no classes, no credentials)."""
        return {
            "core_version": self.core_version,
            "format_version": self.format_version,
            "platform": self.platform,
            "availability": [
                {
                    "adapter_id": item.adapter_id,
                    "candidate_ref": item.candidate_ref,
                    "display_name": item.display_name,
                    "connection_mode": item.connection_mode,
                    "state": item.state,
                    "reasons": list(item.reasons),
                    "version": item.version,
                    "architecture": item.architecture,
                    "build_identity": item.build_identity,
                    "trust": item.trust,
                    "source": item.source,
                    "qualification": item.qualification,
                    "containment": item.containment,
                }
                for item in self.availability
            ],
        }


def _platform_key(platform: str | None) -> str:
    platform = platform or sys.platform
    if platform.startswith("freebsd"):
        platform = "freebsd"
    return platform


def evaluate_runtime_availability(
        candidates: "Inventory | Iterable[InstallationCandidate]",
        *, platform: str | None = None) -> AvailabilityReport:
    """Assess every candidate technically, passively, per entry.

    ``candidates`` is an :class:`~nexus_connector_core.models.Inventory`
    (from ``runtime.discover``) or any iterable of
    :class:`~nexus_connector_core.models.InstallationCandidate`.
    ``platform`` defaults to the EXECUTING host's platform; a remote
    renderer never substitutes its own.

    Unknown adapter IDs raise the typed ``CAPABILITY_UNSUPPORTED``
    error (garbage in the inventory is a caller bug, not a row);
    recoverable per-family conditions are expressed in that family's
    entry instead of discarding the inventory. Two builds of one
    family are never merged. ``READY_FOR_RUNTIME`` is a TECHNICAL
    statement only - the agent's authorization stays in the Server.
    """
    if isinstance(candidates, Inventory):
        items = tuple(candidates.candidates)
    else:
        items = tuple(candidates)
    from . import __version__  # local: avoid import cycles at load
    host = _platform_key(platform)
    catalog = get_runtime_catalog()
    descriptors = {d.adapter_id: d for d in catalog.runtimes}

    # Containment is a HOST property: evaluated once, passively - and
    # only the EXECUTION host can verify it. A report produced for a
    # platform that is not this OS states "unverified" (never READY
    # by omission); the Core on that host publishes its own report.
    local = _platform_key(None)
    if host == local:
        preflight = containment_preflight(platform=host)
        missing_containment = sorted(name for name, status
                                     in preflight.items()
                                     if status != "ok")
        containment = ("unavailable" if missing_containment
                       else "available" if preflight
                       else "unverified")
    else:
        preflight = {}
        missing_containment = []
        containment = "unverified"

    rows: list[CandidateAvailability] = []
    seen: set[str] = set()
    for candidate in items:
        if not isinstance(candidate, InstallationCandidate):
            raise CoreError("VALIDATION_ERROR", "runtime_availability")
        descriptor = descriptors.get(candidate.adapter_id)
        if descriptor is None:
            raise CoreError("CAPABILITY_UNSUPPORTED",
                            "runtime_availability",
                            message=f"unknown adapter_id "
                                    f"{candidate.adapter_id!r}")
        seen.add(candidate.adapter_id)

        reasons: list[str] = []
        qualification = "not_probed"

        # 1. Platform: the implementation must cover the EXECUTION host.
        if host not in descriptor.implementation_platforms:
            reasons.append(f"platform_not_implemented:{host}")

        # 2. Attach is registered, never qualified by existing.
        if descriptor.connection_mode == "attach":
            reasons.append("attach_not_qualified")
            qualification = "unqualified"
        elif (candidate.version is not None
                and candidate.architecture is not None):
            qualified = qualified_build(
                descriptor.native_kind, candidate.version, host,
                candidate.architecture, candidate.fingerprint,
                build_identity=candidate.build_identity)
            qualification = "qualified" if qualified else "unqualified"
            if not qualified:
                reasons.append("build_not_qualified")
        else:
            # Absence of a probe stays inconclusive - never READY.
            reasons.append("no_build_observation")

        # 3. Containment backend of the EXECUTION host.
        if missing_containment:
            for name in missing_containment:
                reasons.append(f"containment_unavailable:{name}")
        elif containment == "unverified":
            reasons.append(f"containment_unverified:{host}")

        # 4. Preparation: the host still owes a trust selection.
        if candidate.trust != "selected":
            reasons.append("selection_required")

        state = READY_FOR_RUNTIME
        if reasons:
            for blocking in _BLOCKING_ORDER:
                if any(reason.startswith(
                        _STATE_PREFIX[blocking]) for reason in reasons):
                    state = blocking
                    break
        rows.append(CandidateAvailability(
            adapter_id=candidate.adapter_id,
            candidate_ref=candidate.fingerprint,
            display_name=descriptor.display_name,
            connection_mode=descriptor.connection_mode,
            state=state,
            reasons=tuple(reasons),
            version=candidate.version,
            architecture=candidate.architecture,
            build_identity=candidate.build_identity,
            trust=candidate.trust,
            source=candidate.source,
            qualification=qualification,
            containment=containment,
        ))

    # Discoverable catalog adapters with no candidate stay visible as
    # NOT_INSTALLED - the catalog remains the single type source.
    for descriptor in catalog.runtimes:
        if descriptor.discoverable and descriptor.adapter_id not in seen:
            rows.append(CandidateAvailability(
                adapter_id=descriptor.adapter_id,
                candidate_ref="",
                display_name=descriptor.display_name,
                connection_mode=descriptor.connection_mode,
                state=NOT_INSTALLED,
                reasons=("no_installed_candidate",),
                version=None,
                architecture=None,
                build_identity=None,
                trust="",
                source="",
                qualification="not_probed",
                containment=containment,
            ))

    return AvailabilityReport(
        core_version=__version__,
        format_version=AVAILABILITY_FORMAT_VERSION,
        platform=host,
        availability=tuple(rows),
    )


_STATE_PREFIX = {
    UNSUPPORTED_PLATFORM: "platform_not_implemented:",
    UNQUALIFIED_BUILD: ("attach_not_qualified", "build_not_qualified"),
    NOT_PROBED: ("no_build_observation",),
    CONTAINMENT_UNAVAILABLE: ("containment_unavailable:",
                              "containment_unverified:"),
    PREPARATION_REQUIRED: "selection_required",
}


__all__ = [
    "AVAILABILITY_FORMAT_VERSION", "AvailabilityReport",
    "CandidateAvailability", "evaluate_runtime_availability",
    "NOT_INSTALLED", "UNSUPPORTED_PLATFORM", "NOT_PROBED",
    "UNQUALIFIED_BUILD", "CONTAINMENT_UNAVAILABLE",
    "PREPARATION_REQUIRED", "READY_FOR_RUNTIME",
]
