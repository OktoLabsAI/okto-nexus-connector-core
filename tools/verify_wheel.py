"""Install a local wheel into a clean venv and import every extracted adapter."""

from __future__ import annotations

import subprocess
import sys
import hashlib
import json
import tarfile
import tempfile
import venv
import ast
import zipfile
from pathlib import Path


def verify_import_boundaries(source: bytes | str, name: str) -> None:
    """Fail on application imports or undeclared third-party wheel imports."""
    tree = ast.parse(source, filename=name)
    allowed_external = {"rfc8785", "jsonschema"}

    def dotted(expression: ast.expr) -> str:
        if isinstance(expression, ast.Name):
            return expression.id
        if isinstance(expression, ast.Attribute):
            return dotted(expression.value) + "." + expression.attr
        return ""

    for node in ast.walk(tree):
        modules = ([alias.name for alias in node.names]
                   if isinstance(node, ast.Import) else
                   [node.module or ""] if isinstance(node, ast.ImportFrom) and
                   node.level == 0 else [])
        if any(module.startswith(("okto_nexus", "okto_nexus_connector"))
               for module in modules):
            raise RuntimeError(f"application import inside wheel: {name}")
        unknown = {module.split(".", 1)[0] for module in modules
                   if module and module.split(".", 1)[0] not in
                   sys.stdlib_module_names | {"nexus_connector_core"} |
                   allowed_external}
        if unknown:
            raise RuntimeError(f"undeclared external imports in {name}: {sorted(unknown)}")
        if not isinstance(node, ast.Call):
            continue
        call = dotted(node.func)
        if call in {"sys.path.append", "sys.path.insert", "sys.path.extend",
                    "sys.path.__setitem__"}:
            raise RuntimeError(f"runtime import-path mutation inside wheel: {name}")
        if call.endswith((".spec_from_file_location", ".SourceFileLoader",
                          ".run_path")):
            raise RuntimeError(f"file-based dynamic import inside wheel: {name}")
        if call == "__import__" or call == "import_module" or call.endswith(".import_module"):
            target = node.args[0] if node.args else None
            literal = target.value if isinstance(target, ast.Constant) and isinstance(
                target.value, str) else None
            package = next((keyword.value.value for keyword in node.keywords
                            if keyword.arg == "package" and
                            isinstance(keyword.value, ast.Constant) and
                            isinstance(keyword.value.value, str)), None)
            if literal is None:
                # The Core-owned registry selects only from a static table of
                # relative module names; no other variable import is allowed.
                if not (name.replace("\\", "/").endswith(
                        "nexus_connector_core/native/registry.py") and
                        call != "__import__" and
                        package == "nexus_connector_core.native"):
                    raise RuntimeError(f"unbounded dynamic import inside wheel: {name}")
            elif literal.startswith("."):
                if package is None or not package.startswith("nexus_connector_core"):
                    raise RuntimeError(f"non-Core relative import inside wheel: {name}")
            elif literal.split(".", 1)[0] not in (
                    sys.stdlib_module_names | {"nexus_connector_core"} |
                    allowed_external):
                raise RuntimeError(f"non-Core dynamic import inside wheel: {name}")


def main() -> None:
    root = Path(__file__).resolve().parents[1]
    wheels = sorted((root / "dist").glob("nexus_connector_core-*.whl"))
    if len(wheels) != 1:
        raise SystemExit("expected exactly one local wheel in dist/")
    sdists = sorted((root / "dist").glob("nexus_connector_core-*.tar.gz"))
    if len(sdists) != 1:
        raise SystemExit("expected exactly one local sdist in dist/")
    with tarfile.open(sdists[0], "r:gz") as archive:
        names = archive.getnames()
        if not any(name.endswith("/contracts/generate.py") for name in names):
            raise RuntimeError("contract generator missing from sdist")
        if not any(name.endswith("/tools/build_artifacts.py") for name in names):
            raise RuntimeError("repeatable build entry point missing from sdist")
        if not any(name.endswith("/tools/consumer_smoke.py") for name in names):
            raise RuntimeError("consumer smoke entry point missing from sdist")
        if not any(name.endswith("/tools/validate_release.py") for name in names):
            raise RuntimeError("release validation entry point missing from sdist")
        if not any(name.endswith("/tools/verify_offline_artifacts.py") for name in names):
            raise RuntimeError("offline artifact entry point missing from sdist")
        for guide in ("api", "lifecycle", "compatibility", "adapters", "security"):
            if not any(name.endswith(f"/docs/{guide}.md") for name in names):
                raise RuntimeError(f"{guide} public guide missing from sdist")
        for required in ("frame", "intent", "event", "error", "inventory",
                         "capability", "http-response"):
            if not any(name.endswith(f"/contracts/nxl/v1/{required}.schema.json")
                       for name in names):
                raise RuntimeError(f"{required} schema missing from sdist")
        if not any(name.endswith("/contracts/nxl/v1/hash-vectors.json")
                   for name in names):
            raise RuntimeError("hash vectors missing from sdist")
        for required in ("index.js", "package.json"):
            if not any(name.endswith(f"/pi_extension/{required}") for name in names):
                raise RuntimeError(f"Pi extension {required} missing from sdist")
        if not any(name.endswith("/native/codex_app_server_0_157_0.schemas.json")
                   for name in names):
            raise RuntimeError("pinned Codex schema missing from sdist")
    with zipfile.ZipFile(wheels[0]) as archive:
        for required in ("index.js", "package.json"):
            if f"nexus_connector_core/pi_extension/{required}" not in archive.namelist():
                raise RuntimeError(f"Pi extension {required} missing from wheel")
        if "nexus_connector_core/native/codex_app_server_0_157_0.schemas.json" not in archive.namelist():
            raise RuntimeError("pinned Codex schema missing from wheel")
        for name in archive.namelist():
            if not name.startswith("nexus_connector_core/") or not name.endswith(".py"):
                continue
            verify_import_boundaries(archive.read(name), name)
    with tempfile.TemporaryDirectory(prefix="nexus-core-wheel-") as directory:
        venv.create(directory, with_pip=True)
        python = Path(directory) / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")
        subprocess.run([str(python), "-m", "pip", "install",
                        "--disable-pip-version-check", str(wheels[0])], check=True)
        code = """
import hashlib, json
from importlib.resources import files
from nexus_connector_core import RuntimeCore, LocalRuntimeCore, OperationReceipt, RuntimeEvent, submit_frame_intent_hash
from nexus_connector_core.native.adapters import codex, pi, claude_code_stream, claude_code_attach
from nexus_connector_core.native.runtime_bridge import CopiedAdapterFactory
from nexus_connector_core.native.redaction import NativeSecretRedactor
from nexus_connector_core.receipt_reducer import receipt_frame, reduce_receipt
from nexus_connector_core.event_reducer import event_batch_frame, reduce_durable_event_batch, event_ack_frame
from nexus_connector_core.inventory_reducer import InventoryCandidate, inventory_snapshot_frame, reduce_inventory
from nexus_connector_core.lease_reducer import LeaseRenewalAttempt, lease_granted_frame, reduce_lease_grant
from nexus_connector_core.conformance import verify_contract_bundle
from nexus_connector_core.testing import run_journal_conformance
from nexus_connector_core.journal import SQLiteJournal
from nexus_connector_core.native.registry import adapter_specs, load_adapter
from nexus_connector_core.native_action_bridge import ScopedNativeActionBridge, NativeActionGrant, ContextGet, HandoffClaim, HandoffComplete
from nexus_connector_core.native_action_socket import NativeActionSocketService
from nexus_connector_core.pi_extension_resource import pi_extension_path
from nexus_connector_core.native.process import spawn_owned_process
from nexus_connector_core.config_document import plan_json_entry, plan_json_entry_removal, apply_json_plan, plan_codex_toml_entry, apply_toml_plan
from nexus_connector_core.config_persistence import apply_json_plan_file, apply_toml_plan_file
from nexus_connector_core.frame_codec import decode_frame, encode_frame
from nexus_connector_core.harness_config import direct_http_config, harness_http_template, render_codex_toml_fragment
folder = files('nexus_connector_core.contracts.nxl.v1')
codex_schema = files('nexus_connector_core.native').joinpath('codex_app_server_0_157_0.schemas.json')
assert hashlib.sha256(codex_schema.read_bytes()).hexdigest() == '2719fccd25a97a7ce355497ca5e9123a63f6dce7f9f83724a5b73fd927811f59'
manifest = json.loads(folder.joinpath('manifest.json').read_text(encoding='utf-8'))
fixtures = json.loads(folder.joinpath('fixtures.json').read_text(encoding='utf-8'))
frame = fixtures['frames']['valid'][0]
assert decode_frame(encode_frame(frame)) == frame
submit = next(item for item in fixtures['frames']['valid'] if item['type'] == 'operation.submit')
assert submit_frame_intent_hash(submit) == submit['intent_hash']
assert len(adapter_specs()) == 4
assert pi_extension_path().is_file()
assert NativeSecretRedactor().clean('nxs_opaque') == '[REDACTED]'
receipt = receipt_frame(OperationReceipt(
    'op', 'sha256:' + 'a' * 64, 'SUCCEEDED', True, False, 'session'),
    server_id='server', executor_id='executor')
assert reduce_receipt(None, receipt).receipt.stage == 'SUCCEEDED'
event = RuntimeEvent(
    'server', 'executor', 'session', 'epoch', 1, 'lifecycle', None, {})
assert event_ack_frame(reduce_durable_event_batch(
    None, event_batch_frame([event])))['sequence'] == 1
inventory = inventory_snapshot_frame(server_id='server', executor_id='executor',
                                     revision=1, candidates=[InventoryCandidate(
                                         'candidate', 'pi_rpc', 'sha256:' + '0' * 64,
                                         'selected')])
assert reduce_inventory(None, inventory).revision == 1
attempt = LeaseRenewalAttempt('server', 'executor', 'binding', 'agent',
                              'session', 'lease-one', 1, 1, 1, 'boot', 10.0)
assert reduce_lease_grant(None, attempt, lease_granted_frame(
    attempt, valid_for_ms=2000, session_owner_generation=1),
    received_at_monotonic=10.1).deadline_monotonic == 11.5
assert verify_contract_bundle(
    'sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630',
    allow_development_partial=True).checked_files == 9
import asyncio, tempfile
from pathlib import Path
async def check_journal():
    with tempfile.TemporaryDirectory() as directory:
        journal = SQLiteJournal(Path(directory) / 'journal.db')
        try:
            assert (await run_journal_conformance(journal)).acknowledged_sequence == 4
        finally:
            journal.close()
asyncio.run(check_journal())
template = harness_http_template('codex_app_server', 'https://nexus.example.test/mcp',
                                 'mcp-cap:wheel', entry_name='okto-nexus',
                                 harness_is_local=False,
                                 approved_origins={'https://nexus.example.test'},
                                 format_qualified=True)
assert 'okto-nexus' in apply_toml_plan(plan_codex_toml_entry(None, template), None).decode()
for name, expected in manifest['files'].items():
    assert 'sha256:' + hashlib.sha256(folder.joinpath(name).read_bytes()).hexdigest() == expected
print('clean wheel import and contract resources OK')
"""
        subprocess.run([str(python), "-I", "-c", code], cwd=directory, check=True)
        consumer_source = (root / "tools" / "consumer_smoke.py").read_text(
            encoding="utf-8")
        wheel_sha = "sha256:" + hashlib.sha256(wheels[0].read_bytes()).hexdigest()
        pinned_manifest = "sha256:a4fd84304de7ba12041721c07f4edce29d3f39d17d8bd24f375de24b0a728630"
        for role in ("embedded", "remote"):
            result = subprocess.run(
                [str(python), "-I", "-c", consumer_source,
                 role, pinned_manifest, wheel_sha],
                cwd=directory, capture_output=True, text=True)
            if result.returncode:
                raise RuntimeError(
                    f"{role} clean-wheel consumer failed: {result.stderr}")
            report = json.loads(result.stdout)
            if report != {"role": role, "wheel_sha256": wheel_sha}:
                raise RuntimeError(f"{role} consumer used an unexpected wheel")
        print("embedded and remote clean-wheel consumer smokes OK")


if __name__ == "__main__":
    main()
