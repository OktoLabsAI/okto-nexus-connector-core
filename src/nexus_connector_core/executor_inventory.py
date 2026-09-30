"""Path-free, versioned executor inventory shared by the two hosts.

The producing host keeps the complete InstallationCandidate objects.  Only
this projection crosses HTTP; the receiver never resolves a remote path.
"""

from __future__ import annotations

import hashlib
import json
from importlib.resources import files
from functools import lru_cache
from jsonschema import Draft202012Validator
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
from .native.registry import adapter_specs
from .native.adapters.compatibility import qualified_build

SNAPSHOT_FORMAT_VERSION = 2
MAX_SNAPSHOT_CANDIDATES = 128
MAX_OBSERVATION_AGE_MS = 300_000


def get_executor_inventory_schema() -> dict[str, Any]:
    """Return an independent copy of the manifest-verified current HTTP schema."""
    from .frame_codec_r4 import verify_r4_development_bundle
    verify_r4_development_bundle()
    return json.loads(files("nexus_connector_core.contracts.nxl.r4").joinpath(
        "inventory.schema.json").read_text(encoding="utf-8"))


@lru_cache(maxsize=1)
def _inventory_validator() -> Draft202012Validator:
    schema = get_executor_inventory_schema()
    Draft202012Validator.check_schema(schema)
    return Draft202012Validator(schema)


def _invalid(message: str) -> CoreError:
    return CoreError("VALIDATION_ERROR", "executor_inventory", retry_safe=True,
                     message=message)


def _qualified_controls(evidence: Mapping[str, Any], platform: str) -> list[str]:
    spec = next((s for s in adapter_specs() if s.adapter_id == evidence["adapter_id"]), None)
    if (spec is None or spec.mode != "managed" or platform not in spec.platforms or
            not qualified_build(spec.native_kind, evidence["version"], platform,
                                evidence["architecture"], evidence["content_fingerprint"],
                                control=True, build_identity=evidence["build_identity"])):
        return []
    return sorted(c.action for c in spec.control_targeting if c.supported)


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
                "control_targeting": [control.to_dict() for control in item.control_targeting],
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
            ({**{key: row[key] for key in (
                "adapter_id", "harness_family", "native_kind",
                "connection_mode", "implementation_platforms",
                "support_status", "discoverable")},
              **({"control_targeting": sorted(row["control_targeting"], key=lambda c: c["action"])}
                 if snapshot["snapshot_format_version"] == 2 else {})}
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
            "state": row["state"],
            "reasons": sorted(row["reasons"]),
            "support_status": next(r["support_status"] for r in catalog["runtimes"]
                                   if r["adapter_id"] == item.adapter_id),
            "platform": report.platform,
            # Passive inventory has no observed session capability report.
            "capability_report": None,
            "qualification": row["qualification"],
            "containment": row["containment"],
        })
        evidence[-1]["qualified_control_actions"] = _qualified_controls(evidence[-1], report.platform)
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
    verify_executor_inventory_snapshot(snapshot)
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


def verify_executor_inventory_snapshot(snapshot: Mapping[str, Any], *,
                                       allow_historical: bool = False) -> None:
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
        version = snapshot["snapshot_format_version"]
        if type(version) is not int or (version != SNAPSHOT_FORMAT_VERSION and
                                       not (allow_historical and version == 1)):
            raise ValueError("unsupported snapshot format")
        if version == 2 and not _inventory_validator().is_valid(snapshot):
            raise ValueError("inventory does not match the current Core schema")
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
                catalog["format_version"] != (1 if version == 1 else CATALOG_FORMAT_VERSION) or
                set(availability) != {"core_version", "format_version",
                                      "platform", "availability"} or
                availability["format_version"] != AVAILABILITY_FORMAT_VERSION):
            raise ValueError("catalog or availability format is incompatible")
        catalog_fields = {"adapter_id", "display_name", "harness_family",
                          "native_kind", "connection_mode",
                          "implementation_platforms", "support_status",
                          "discoverable"}
        if version == 2:
            catalog_fields.add("control_targeting")
        if any(set(row) != catalog_fields for row in catalog["runtimes"]):
            raise ValueError("unexpected catalog fields")
        if version == 2:
            expected = {r.adapter_id: [c.to_dict() for c in r.control_targeting]
                        for r in get_runtime_catalog().runtimes}
            if any(canonical_json(row["control_targeting"]) != canonical_json(expected.get(row["adapter_id"]))
                   for row in catalog["runtimes"]):
                raise ValueError("control targeting differs from the Core contract")
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
        if version == 2:
            evidence_fields -= {"technical_state", "technical_reasons"}
            evidence_fields |= {"qualified_control_actions", "state", "reasons",
                                "support_status", "platform", "capability_report"}
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
            if version == 2 and row["qualified_control_actions"] != _qualified_controls(row, availability["platform"]):
                raise ValueError("control qualification differs from the exact build evidence")
            available = rows[row["adapter_id"], row["candidate_ref"]]
            state_key = "state" if version == 2 else "technical_state"
            reasons_key = "reasons" if version == 2 else "technical_reasons"
            if version == 2:
                descriptor = next(r for r in catalog["runtimes"] if r["adapter_id"] == row["adapter_id"])
                if (row["platform"] != availability["platform"] or
                        row["support_status"] != descriptor["support_status"] or
                        row["capability_report"] is not None):
                    raise ValueError("passive candidate evidence differs from the catalog")
            if row[reasons_key] != sorted(available["reasons"]):
                raise ValueError("availability and evidence reasons differ")
            if any((row[evidence_key] != available[availability_key])
                   for evidence_key, availability_key in (
                       (state_key, "state"),
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
    except (KeyError, TypeError, ValueError, AttributeError, StopIteration) as exc:
        raise _invalid(str(exc)) from exc


__all__ = ["SNAPSHOT_FORMAT_VERSION", "MAX_SNAPSHOT_CANDIDATES",
           "get_executor_inventory_schema",
           "build_executor_inventory_snapshot", "calculate_inventory_revision",
           "verify_executor_inventory_snapshot"]
