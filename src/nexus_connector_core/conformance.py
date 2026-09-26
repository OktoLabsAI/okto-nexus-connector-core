"""Offline consumer verification of the Core-owned NXL contract bundle."""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from dataclasses import dataclass
from importlib.resources import files
from typing import Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from .frame_codec import decode_frame
from .models import CoreError
from .protocol import (CONTRACT_REVISION, PROTOCOL_MAJOR, canonical_json,
                       strict_json)

_BUNDLE_FILES = frozenset({
    "frame.schema.json", "intent.schema.json", "event.schema.json",
    "error.schema.json", "inventory.schema.json", "capability.schema.json",
    "http-response.schema.json", "fixtures.json", "hash-vectors.json",
})
_HASH = re.compile(r"sha256:[0-9a-f]{64}\Z", re.ASCII)
_MAX_RESOURCE_BYTES = 1024 * 1024


@dataclass(frozen=True, slots=True)
class BundleVerification:
    manifest_sha256: str
    revision: str
    status: str
    checked_files: int
    checked_frames: int
    checked_models: int
    checked_vectors: int


def _fail() -> None:
    raise CoreError("CONTRACT_MISMATCH", "bundle_conformance")


def _json(data: bytes) -> Any:
    if len(data) > _MAX_RESOURCE_BYTES:
        _fail()
    try:
        return strict_json(data.decode("utf-8", errors="strict"))
    except (UnicodeError, ValueError, RecursionError) as exc:
        raise CoreError("CONTRACT_MISMATCH", "bundle_conformance") from exc


def verify_contract_bundle(expected_manifest_sha256: str, *,
                           expected_revision: str = CONTRACT_REVISION,
                           allow_development_partial: bool = False) -> BundleVerification:
    """Verify a pinned installed bundle without network or source checkout.

    Consumers must pin the expected manifest SHA-256 from a reviewed release.
    The current dev bundle requires explicit opt-in and is not normative.
    """
    if (not isinstance(expected_manifest_sha256, str) or
            not _HASH.fullmatch(expected_manifest_sha256) or
            not isinstance(expected_revision, str) or
            type(allow_development_partial) is not bool):
        _fail()
    try:
        folder = files("nexus_connector_core.contracts.nxl.v1")
        manifest_data = folder.joinpath("manifest.json").read_bytes()
    except (OSError, ModuleNotFoundError) as exc:
        raise CoreError("CONTRACT_MISMATCH", "bundle_conformance") from exc
    if (len(manifest_data) > _MAX_RESOURCE_BYTES or
            "sha256:" + hashlib.sha256(manifest_data).hexdigest() !=
            expected_manifest_sha256):
        _fail()
    manifest = _json(manifest_data)
    if (not isinstance(manifest, dict) or
            manifest.get("revision") != expected_revision or
            manifest.get("revision") != CONTRACT_REVISION or
            manifest.get("protocol_major") != PROTOCOL_MAJOR or
            not isinstance(manifest.get("files"), dict) or
            set(manifest["files"]) != _BUNDLE_FILES):
        _fail()
    status = manifest.get("status")
    if status != "normative" and not (allow_development_partial and
                                       status == "development-partial"):
        _fail()
    resources: dict[str, bytes] = {}
    for name, expected in manifest["files"].items():
        if not isinstance(expected, str) or not _HASH.fullmatch(expected):
            _fail()
        try:
            data = folder.joinpath(name).read_bytes()
        except OSError as exc:
            raise CoreError("CONTRACT_MISMATCH", "bundle_conformance") from exc
        if (len(data) > _MAX_RESOURCE_BYTES or
                "sha256:" + hashlib.sha256(data).hexdigest() != expected):
            _fail()
        resources[name] = data
    schemas = {name: _json(resources[f"{name}.schema.json"])
               for name in ("frame", "intent", "event", "error", "inventory",
                            "capability", "http-response")}
    try:
        validators = {}
        for name, schema in schemas.items():
            Draft202012Validator.check_schema(schema)
            validators[name] = Draft202012Validator(schema)
    except Exception as exc:
        raise CoreError("CONTRACT_MISMATCH", "bundle_conformance") from exc
    fixtures = _json(resources["fixtures.json"])
    vectors = _json(resources["hash-vectors.json"])
    if (not isinstance(fixtures, dict) or
            fixtures.get("revision") != expected_revision or
            not isinstance(vectors, dict) or
            vectors.get("revision") != expected_revision):
        _fail()
    checked_frames = 0
    checked_models = 0
    try:
        for frame in fixtures["frames"]["valid"]:
            validators["frame"].validate(frame)
            decode_frame(canonical_json(frame))
            checked_frames += 1
        for frame in fixtures["frames"]["invalid"]:
            try:
                validators["frame"].validate(frame)
            except ValidationError:
                checked_frames += 1
            else:
                _fail()
        for name, cases in fixtures["models"].items():
            if name not in validators or name == "frame":
                _fail()
            for item in cases["valid"]:
                validators[name].validate(item)
                checked_models += 1
            for item in cases["invalid"]:
                try:
                    validators[name].validate(item)
                except ValidationError:
                    checked_models += 1
                else:
                    _fail()
        checked_vectors = 0
        for vector in vectors["vectors"]:
            encoded = canonical_json(vector["input"])
            if (encoded.decode("utf-8") != vector["canonical"] or
                    "sha256:" + hashlib.sha256(encoded).hexdigest() !=
                    vector["sha256"]):
                _fail()
            checked_vectors += 1
    except (KeyError, TypeError, ValueError, ValidationError,
            RecursionError, CoreError) as exc:
        raise CoreError("CONTRACT_MISMATCH", "bundle_conformance") from exc
    return BundleVerification(expected_manifest_sha256, expected_revision,
                              status, len(resources), checked_frames,
                              checked_models, checked_vectors)


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify the installed NXL bundle offline")
    parser.add_argument("--manifest-sha256", required=True)
    parser.add_argument("--revision", default=CONTRACT_REVISION)
    parser.add_argument("--allow-development-partial", action="store_true")
    args = parser.parse_args()
    try:
        report = verify_contract_bundle(
            args.manifest_sha256, expected_revision=args.revision,
            allow_development_partial=args.allow_development_partial)
    except CoreError as exc:
        parser.exit(1, f"{exc.code}\n")
    print(json.dumps({
        "manifest_sha256": report.manifest_sha256,
        "revision": report.revision, "status": report.status,
        "checked_files": report.checked_files,
        "checked_frames": report.checked_frames,
        "checked_models": report.checked_models,
        "checked_vectors": report.checked_vectors,
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
