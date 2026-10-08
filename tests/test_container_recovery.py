from dataclasses import replace
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

from nexus_connector_core.models import ProcessBirthEvidence
from nexus_connector_core.native.process import spawn_owned_process, snapshot_owned_process_birth
from nexus_connector_core.native.process.recovery import recover_owned_container
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession


@pytest.mark.skipif(sys.platform not in {'win32', 'linux'}, reason='Durable container recovery')
def test_container_proof_survives_abrupt_owner_exit(tmp_path):
    evidence_file = tmp_path / 'birth.json'
    source = str(Path(__file__).resolve().parents[1] / 'src')
    script = '''
import sys, os, json
from dataclasses import asdict
from pathlib import Path
sys.path.insert(0, sys.argv[1])
from nexus_connector_core.native.process import spawn_owned_process, snapshot_owned_process_birth
child = spawn_owned_process([sys.executable, '-c', 'import time; time.sleep(60)'],
    cwd=os.getcwd(), env=dict(os.environ), text=True)
Path(sys.argv[2]).write_text(json.dumps(asdict(snapshot_owned_process_birth(child))))
os._exit(7)
'''
    owner = subprocess.run([sys.executable, '-c', script, source, str(evidence_file)], timeout=10)
    assert owner.returncode == 7
    evidence = ProcessBirthEvidence(**json.loads(evidence_file.read_text()))
    assert recover_owned_container(evidence, stop=True) == 'STOPPED'


@pytest.mark.skipif(sys.platform != 'win32', reason='Windows container recovery')
def test_named_container_recovery_observes_and_stops_only_owned_tree():
    process = spawn_owned_process([sys.executable,'-c','import time; time.sleep(60)'], env=dict(os.environ), cwd=os.getcwd(), text=True)
    other = spawn_owned_process([sys.executable,'-c','import time; time.sleep(60)'], env=dict(os.environ), cwd=os.getcwd(), text=True)
    try:
        evidence = snapshot_owned_process_birth(process)
        assert recover_owned_container(replace(evidence,container_id=None),stop=True) == 'UNKNOWN'
        assert recover_owned_container(evidence) == 'RUNNING'
        assert recover_owned_container(evidence,stop=True) == 'STOPPED'
        process.wait(timeout=5)
        assert other.poll() is None
        assert recover_owned_container(evidence,stop=True) == 'STOPPED'
    finally:
        process.kill(); process.wait(timeout=5)
        other.kill(); other.wait(timeout=5)


@pytest.mark.parametrize('adapter', ['codex','pi'])
@pytest.mark.skipif(sys.platform not in {'win32','linux'}, reason='Qualified contained launch')
def test_transport_owned_process_has_birth_evidence(adapter):
    from nexus_connector_core.native.adapters.codex import CodexAppServerConnector
    from nexus_connector_core.native.adapters.pi import PiRpcConnector
    cls = CodexAppServerConnector if adapter == 'codex' else PiRpcConnector
    connector = cls.__new__(cls)
    process = spawn_owned_process([sys.executable,'-c','import time; time.sleep(60)'], env=dict(os.environ), cwd=os.getcwd(), text=True)
    connector._transport = SimpleNamespace(_proc=process)
    try:
        session = SimpleNamespace(_connector=connector)
        assert CopiedAdapterSession.owned_process_birth(session) == snapshot_owned_process_birth(process)
    finally:
        process.kill(); process.wait(timeout=5)
