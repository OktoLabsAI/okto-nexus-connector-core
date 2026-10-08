"""Close reports require native tree-stop proof and preserve force provenance."""
import asyncio
import subprocess
import sys
import threading
from concurrent.futures import ThreadPoolExecutor

import pytest
from nexus_connector_core.native.adapters.codex import _CodexTransport
from nexus_connector_core.native.adapters.pi import _PiTransport, PiRpcConnector
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native.runtime_bridge import CopiedAdapterSession
from nexus_connector_core.native.adapter_types import HarnessSession, HarnessCapabilities
from nexus_connector_core.native.adapter_types import NativeAdapterError
from test_native_runtime_bridge import context, FakeCopiedConnector


class Process:
    def __init__(self, *, timeout=False, tree_stopped=True):
        self.timeout = timeout
        self.tree_stopped = tree_stopped
        self.stopped = False
        self.signals = []

    def poll(self):
        return 0 if self.stopped else None

    def terminate(self):
        self.signals.append("terminate")
        self.stopped = True

    def kill(self):
        self.signals.append("kill")
        self.stopped = True

    def wait(self, timeout):
        if self.timeout and not self.stopped:
            raise subprocess.TimeoutExpired("native", timeout)
        self.stopped = True
        return 0


@pytest.mark.parametrize("tree_stopped", [False, True])
def test_codex_close_reports_confirmed_containment(tree_stopped):
    transport = object.__new__(_CodexTransport)
    transport._closed = threading.Event()
    transport._termination_requested = threading.Event()
    transport._proc = Process(tree_stopped=tree_stopped)
    transport._fail_pending = lambda reason: None
    assert transport.close() == ("forced" if tree_stopped else "unknown")
    assert transport._proc.signals == ["terminate"]


@pytest.mark.parametrize('tree_stopped', [False, True])
@pytest.mark.parametrize('already_exited', [False, True])
def test_pi_close_reports_tree_proof_and_retains_force_provenance(tree_stopped, already_exited):
    transport = object.__new__(_PiTransport)
    transport._closed = threading.Event()
    transport._termination_requested = threading.Event()
    transport._proc = Process(tree_stopped=tree_stopped)
    transport._proc.stopped = already_exited
    transport._fail_all_pending = lambda reason: None
    connector = object.__new__(PiRpcConnector)
    connector._transport = transport
    connector._closed_event = threading.Event()
    expected = ('graceful' if already_exited else 'forced') if tree_stopped else 'unknown'
    assert connector.close() == expected
    assert connector.close() == expected
    assert transport._proc.signals == ([] if already_exited else ['terminate'])


def test_pi_missing_process_does_not_claim_confirmed_stop():
    transport = object.__new__(_PiTransport)
    transport._closed = threading.Event()
    transport._proc = None
    assert transport.close() == 'unknown'


def test_pi_prior_force_is_not_reclassified_as_graceful():
    transport = object.__new__(_PiTransport)
    transport._closed = threading.Event()
    transport._termination_requested = threading.Event()
    transport._proc = Process()
    transport._fail_all_pending = lambda reason: None
    connector = object.__new__(PiRpcConnector)
    connector._transport = transport
    connector._closed_event = threading.Event()
    connector.force_stop()
    assert connector.close() == 'forced'
    assert transport._proc.signals == ['kill']


@pytest.mark.parametrize('reply', [
    {'success': False, 'error': 'unsupported'},
    {'success': 'true', 'data': {}},
    {'success': True, 'data': []},
])
def test_pi_failed_readiness_retains_proof_of_stopped_process(reply):
    source = ('import sys,json\nfor line in sys.stdin:\n'
        ' msg=json.loads(line)\n'
        f' print(json.dumps(dict(type="response",command=msg["type"],**{reply!r})),flush=True)\n')
    connector = PiRpcConnector(command=[sys.executable, '-u', '-c', source], env={})
    try:
        with pytest.raises(NativeAdapterError, match='protocol_incompatible'):
            connector.start(owning_agent_id='agent')
        assert connector._transport._proc.poll() is not None
        assert connector.close() == 'forced'
        assert connector.close() == 'forced'
        assert list(connector.events()) == []
    finally:
        connector.close()


@pytest.mark.parametrize("timeout", [False, True])
@pytest.mark.parametrize("tree_stopped", [False, True])
def test_claude_distinguishes_eof_from_forced_timeout(timeout, tree_stopped):
    connector = object.__new__(ClaudeCodeStreamConnector)
    connector._termination_requested = threading.Event()
    connector._end = lambda: None
    connector._proc = Process(timeout=timeout, tree_stopped=tree_stopped)
    expected = ("forced" if timeout else "graceful") if tree_stopped else "unknown"
    assert connector.close() == expected
    assert connector._proc.signals == (["kill"] if timeout else [])


def test_claude_prior_force_cannot_be_reclassified_as_graceful():
    connector = object.__new__(ClaudeCodeStreamConnector)
    connector._termination_requested = threading.Event()
    connector._end = lambda: None
    connector._proc = Process()
    connector.force_stop()
    assert connector.close() == "forced"


@pytest.mark.parametrize("reported", ["forced", "graceful", "unknown", None])
@pytest.mark.parametrize("stopped", [False, True])
def test_bridge_requires_stop_proof_for_adapter_report(reported, stopped):
    class Connector(FakeCopiedConnector):
        def send(self, session, command):
            pass

        def close(self):
            self.closed = stopped
            return reported

    async def run():
        harness = HarnessSession("native", "claude_code", "agent", "STARTING",
            HarnessCapabilities(False, None, False, False, True), "2026-09-30T00:00:00Z")
        with ThreadPoolExecutor(max_workers=1) as control, ThreadPoolExecutor(max_workers=1) as force:
            bridge = CopiedAdapterSession(Connector(), harness, session_id="session",
                stream_epoch="epoch", context=context(), control_executor=control,
                force_executor=force)
            expected = reported if stopped and reported in {"forced", "graceful"} else "unknown"
            assert await bridge.close() == expected
    asyncio.run(run())
