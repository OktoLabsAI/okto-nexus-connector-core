"""Path-free, versioned executor inventory shared by the two hosts.

The producing host keeps the complete InstallationCandidate objects.  Only
this projection crosses HTTP; the receiver never resolves a remote path.
"""

from __future__ import annotations

import hashlib
from typing import Any, Iterable, Mapping

from .availability import (
    AVAILABILITY_FORMAT_VERSION,
    AvailabilityReport,
    evaluate_runtime_availability,
)
from .catalog import CATALOG_FORMAT_VERSION, get_runtime_catalog
from .installation import effective_installation_ref
from .models import CoreError, InstallationCandidate
from .protocol import canonical_json

SNAPSHOT_FORMAT_VERSION = 1
MAX_SNAPSHOT_CANDIDATES = 128
MAX_OBSERVATION_AGE_MS = 300_000


def _invalid(message: str) -> CoreError:
    return CoreError("VALIDATION_ERROR", "executor_inventory", retry_safe=True,
                     message=message)


def _catalog_projection() -> dict[str, Any]:
    catalog = get_runtime_catalog()
    return {
        "core_version": catalog.core_version,
        "format_version": catalog.format_version,
        "runtimes": [
            {
                "adapter_id": item.adapter_id,
                "display_name": item.display_name,
                "harness_family": item.harness_family,
                "native_kind": item.native_kind,
                "connection_mode": item.connection_mode,
                "implementation_platforms": sorted(item.implementation_platforms),
                "support_status": item.support_status,
                "discoverable": item.discoverable,
            }
            for item in catalog.runtimes
        ],
    }


def _semantic(snapshot: Mapping[str, Any]) -> dict[str, Any]:
    """Selection evidence only. Publication metadata and labels are excluded."""
    catalog = snapshot["catalog"]
    availability = snapshot["availability"]
    return {
        "snapshot_format_version": snapshot["snapshot_format_version"],
        "core_version": snapshot["core_version"],
        "catalog_format_version": catalog["format_version"],
        "availability_format_version": availability["format_version"],
        "platform": availability["platform"],
        "catalog": sorted(
            ({key: row[key] for key in (
                "adapter_id", "harness_family", "native_kind",
                "connection_mode", "implementation_platforms",
                "support_status", "discoverable")}
             for row in catalog["runtimes"]),
            key=lambda row: row["adapter_id"],
        ),
        "evidence": snapshot["evidence"],
        "availability": sorted(
            ({**{key: row[key] for key in (
                "adapter_id", "candidate_ref", "connection_mode", "state",
                "version", "architecture", "build_identity", "trust",
                "source", "qualification", "containment")},
              "reasons": sorted(row["reasons"])}
             for row in availability["availability"]),
            key=lambda row: (row["adapter_id"], row["candidate_ref"]),
        ),
    }


def _revision(snapshot: Mapping[str, Any]) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(_semantic(snapshot))).hexdigest()


def build_executor_inventory_snapshot(
    candidates: Iterable[InstallationCandidate], *, server_id: str,
    executor_id: str, producer_instance_id: str, publication_sequence: int,
    observation_age_ms: int = 0,
    availability: AvailabilityReport | None = None,
) -> dict[str, Any]:
    """Build an R4 snapshot without losing the original candidate inventory.

    ``availability`` may be supplied when the host has already evaluated the
    same candidates. Its rows must match the candidate refs exactly.
    """
    for name, value in (("server_id", server_id), ("executor_id", executor_id),
                        ("producer_instance_id", producer_instance_id)):
        if not isinstance(value, str) or not 1 <= len(value) <= 160:
            raise _invalid(f"{name} must contain 1..160 characters")
    if type(publication_sequence) is not int or publication_sequence < 1:
        raise _invalid("publication_sequence must be positive")
    if (type(observation_age_ms) is not int or observation_age_ms < 0 or
            observation_age_ms > MAX_OBSERVATION_AGE_MS):
        raise _invalid("observation_age_ms is out of range")
    items = tuple(candidates)
    if len(items) > MAX_SNAPSHOT_CANDIDATES:
        raise _invalid("candidate collection requires pagination")
    if any(not isinstance(item, InstallationCandidate) for item in items):
        raise _invalid("inventory must contain InstallationCandidate objects")

    report = availability or evaluate_runtime_availability(items)
    if report.format_version != AVAILABILITY_FORMAT_VERSION:
        raise _invalid("availability format is incompatible")
    catalog = _catalog_projection()
    if catalog["format_version"] != CATALOG_FORMAT_VERSION:
        raise _invalid("catalog format is incompatible")
    report_data = report.to_dict()
    rows = {(row["adapter_id"], row["candidate_ref"]): row
            for row in report_data["availability"] if row["candidate_ref"]}
    if len(rows) != len(items):
        raise _invalid("availability and candidate inventory differ")

    evidence = []
    seen: set[tuple[str, str]] = set()
    for item in items:
        ref = effective_installation_ref(item)
        key = (item.adapter_id, ref)
        if key in seen or key not in rows:
            raise _invalid("candidate reference is duplicate or unassessed")
        seen.add(key)
        row = rows[key]
        evidence.append({
            "adapter_id": item.adapter_id,
            "candidate_ref": ref,
            "content_fingerprint": item.fingerprint,
            "build_identity": item.build_identity,
            "version": item.version,
            "architecture": item.architecture,
            "trust": item.trust,
            "source": item.source,
            "technical_state": row["state"],
            "technical_reasons": sorted(row["reasons"]),
            "qualification": row["qualification"],
            "containment": row["containment"],
        })
    evidence.sort(key=lambda row: (row["adapter_id"], row["candidate_ref"]))

    snapshot = {
        "snapshot_format_version": SNAPSHOT_FORMAT_VERSION,
        "server_id": server_id,
        "executor_id": executor_id,
        "producer_instance_id": producer_instance_id,
        "publication_sequence": publication_sequence,
        "core_version": catalog["core_version"],
        "catalog": catalog,
        "availability": report_data,
        "evidence": evidence,
        "observation_age_ms": observation_age_ms,
    }
    snapshot["inventory_revision"] = _revision(snapshot)
    return snapshot


def calculate_inventory_revision(
    candidates: Iterable[InstallationCandidate], *,
    availability: AvailabilityReport | None = None,
) -> str:
    """Compute the same complete revision for a local selection preview.

    The preview is not a publishable snapshot: the application supplies the
    real executor/producer identity and publication sequence when publishing.
    """
    return build_executor_inventory_snapshot(
        candidates, server_id="preview", executor_id="preview",
        producer_instance_id="preview", publication_sequence=1,
        availability=availability,
    )["inventory_revision"]


def verify_executor_inventory_snapshot(snapshot: Mapping[str, Any]) -> None:
    """Reject malformed/tampered wire projections before a host stores them.

    Authentication, publication sequence CAS, and freshness are host duties.
    """
    try:
        if set(snapshot) != {
            "snapshot_format_version", "server_id", "executor_id",
            "producer_instance_id", "publication_sequence", "core_version",
            "catalog", "availability", "evidence", "observation_age_ms",
            "inventory_revision",
        }:
            raise ValueError("unexpected snapshot fields")
        if snapshot["snapshot_format_version"] != SNAPSHOT_FORMAT_VERSION:
            raise ValueError("unsupported snapshot format")
        for name in ("server_id", "executor_id", "producer_instance_id"):
            value = snapshot[name]
            if not isinstance(value, str) or not 1 <= len(value) <= 160:
                raise ValueError(f"invalid {name}")
        if type(snapshot["publication_sequence"]) is not int or snapshot["publication_sequence"] < 1:
            raise ValueError("invalid publication sequence")
        age = snapshot["observation_age_ms"]
        if type(age) is not int or not 0 <= age <= MAX_OBSERVATION_AGE_MS:
            raise ValueError("invalid observation age")
        evidence = snapshot["evidence"]
        if not isinstance(evidence, list) or len(evidence) > MAX_SNAPSHOT_CANDIDATES:
            raise ValueError("invalid candidate count")
        catalog = snapshot["catalog"]
        availability = snapshot["availability"]
        if (set(catalog) != {"core_version", "format_version", "runtimes"} or
                catalog["format_version"] != CATALOG_FORMAT_VERSION or
                set(availability) != {"core_version", "format_version",
                                      "platform", "availability"} or
                availability["format_version"] != AVAILABILITY_FORMAT_VERSION):
            raise ValueError("catalog or availability format is incompatible")
        catalog_fields = {"adapter_id", "display_name", "harness_family",
                          "native_kind", "connection_mode",
                          "implementation_platforms", "support_status",
                          "discoverable"}
        if any(set(row) != catalog_fields for row in catalog["runtimes"]):
            raise ValueError("unexpected catalog fields")
        availability_fields = {"adapter_id", "candidate_ref", "display_name",
                               "connection_mode", "state", "reasons", "version",
                               "architecture", "build_identity", "trust", "source",
                               "qualification", "containment", "label"}
        if any(set(row) != availability_fields
               for row in availability["availability"]):
            raise ValueError("unexpected availability fields")
        evidence_fields = {"adapter_id", "candidate_ref", "content_fingerprint",
                           "build_identity", "version", "architecture", "trust",
                           "source", "technical_state", "technical_reasons",
                           "qualification", "containment"}
        if any(set(row) != evidence_fields for row in evidence):
            raise ValueError("unexpected evidence fields")
        refs = [(row["adapter_id"], row["candidate_ref"]) for row in evidence]
        if refs != sorted(set(refs)):
            raise ValueError("candidate refs must be unique and sorted")
        if any(not ref.startswith("nexus-install-v1:") for _, ref in refs):
            raise ValueError("unsupported candidate ref")
        rows = {(row["adapter_id"], row["candidate_ref"]): row
                for row in availability["availability"] if row["candidate_ref"]}
        if set(rows) != set(refs):
            raise ValueError("availability and evidence refs differ")
        for row in evidence:
            available = rows[row["adapter_id"], row["candidate_ref"]]
            if row["technical_reasons"] != sorted(available["reasons"]):
                raise ValueError("availability and evidence reasons differ")
            if any((row[evidence_key] != available[availability_key])
                   for evidence_key, availability_key in (
                       ("technical_state", "state"),
                       ("build_identity", "build_identity"),
                       ("version", "version"),
                       ("architecture", "architecture"),
                       ("trust", "trust"), ("source", "source"),
                       ("qualification", "qualification"),
                       ("containment", "containment"))):
                raise ValueError("availability and evidence differ")
        if snapshot["core_version"] != snapshot["catalog"]["core_version"] or \
                snapshot["core_version"] != snapshot["availability"]["core_version"]:
            raise ValueError("core versions differ")
        if snapshot["inventory_revision"] != _revision(snapshot):
            raise ValueError("inventory revision differs from evidence")
    except (KeyError, TypeError, ValueError, AttributeError) as exc:
        raise _invalid(str(exc)) from exc


__all__ = ["SNAPSHOT_FORMAT_VERSION", "MAX_SNAPSHOT_CANDIDATES",
           "build_executor_inventory_snapshot", "calculate_inventory_revision",
           "verify_executor_inventory_snapshot"]
