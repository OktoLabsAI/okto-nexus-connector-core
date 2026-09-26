import hashlib
import json
import subprocess
import sys
from importlib.resources import files
from pathlib import Path

import pytest

from nexus_connector_core.protocol import canonical_json


def test_bundle_manifest_and_fixtures():
    jsonschema = pytest.importorskip("jsonschema")
    folder = files("nexus_connector_core.contracts.nxl.v1")
    manifest = json.loads(folder.joinpath("manifest.json").read_text(encoding="utf-8"))
    fixtures = json.loads(folder.joinpath("fixtures.json").read_text(encoding="utf-8"))
    for name, expected in manifest["files"].items():
        actual = hashlib.sha256(folder.joinpath(name).read_bytes()).hexdigest()
        assert "sha256:" + actual == expected
    assert fixtures["revision"] == manifest["revision"]
    schemas = {
        name: json.loads(folder.joinpath(name + ".schema.json").read_text(encoding="utf-8"))
        for name in ("frame", "intent", "event", "error", "inventory",
                     "capability", "http-response")
    }
    for schema in schemas.values():
        jsonschema.Draft202012Validator.check_schema(schema)
    frame_types = {variant["title"] for variant in schemas["frame"]["oneOf"]}
    assert {frame["type"] for frame in fixtures["frames"]["valid"]} == frame_types
    for frame in fixtures["frames"]["valid"]:
        jsonschema.validate(frame, schemas["frame"])
    for frame in fixtures["frames"]["invalid"]:
        with pytest.raises(jsonschema.ValidationError):
            jsonschema.validate(frame, schemas["frame"])
    for name, cases in fixtures["models"].items():
        for case in cases["valid"]:
            jsonschema.validate(case, schemas[name])
        for case in cases["invalid"]:
            with pytest.raises(jsonschema.ValidationError):
                jsonschema.validate(case, schemas[name])
    vectors = json.loads(folder.joinpath("hash-vectors.json").read_text(encoding="utf-8"))
    assert vectors["revision"] == manifest["revision"]
    for vector in vectors["vectors"]:
        canonical = canonical_json(vector["input"])
        assert canonical.decode("utf-8") == vector["canonical"]
        assert "sha256:" + hashlib.sha256(canonical).hexdigest() == vector["sha256"]


def test_generated_bundle_matches_core_source():
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, str(root / "contracts/generate.py"), "--check"],
                   check=True, cwd=root)
