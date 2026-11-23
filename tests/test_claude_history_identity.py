import pytest
from types import SimpleNamespace

from nexus_connector_core import RuntimeEvent
from nexus_connector_core.native.adapters import claude_code_stream
from nexus_connector_core.native.adapters.claude_code_stream import ClaudeCodeStreamConnector
from nexus_connector_core.native import claude_history_identity
from nexus_connector_core.native.claude_history_identity import CLAUDE_HISTORY_IDENTITY, confirmed_claude_history
from nexus_connector_core.protocol import canonical_json


NATIVE = 'cb41c871-35f9-480f-90c2-f2aa920caf65'
OTHER = '1fde90a3-7d39-4046-8098-2f609acb26c3'


@pytest.mark.parametrize('started,finished,expected', [
    ({'session_id': NATIVE}, {'session_id': NATIVE}, NATIVE),
    ({}, {'session_id': NATIVE}, None),
    ({'session_id': NATIVE}, {}, None),
    ({'session_id': NATIVE}, {'session_id': OTHER}, None),
    ({'session_id': NATIVE.upper()}, {'session_id': NATIVE}, None),
])
def test_history_identity_requires_a_matching_pair_for_the_same_turn(started, finished, expected):
    adapter = ClaudeCodeStreamConnector(binary='unused')
    events = []
    adapter._emit = lambda kind, native, payload, **kwargs: events.append((kind, native, payload))
    adapter._append_pending_turn('reviewed-operation')
    adapter._handle_system({'type': 'system', 'subtype': 'init'} | started)
    adapter._handle_result({'type': 'result', 'subtype': 'success',
        CLAUDE_HISTORY_IDENTITY: {'schema_version': 1, 'session_id': OTHER}} | finished)

    kind, native, payload = events[-1]
    assert (kind, native) == ('turn_completed', 'result:success')
    assert confirmed_claude_history(payload.get(CLAUDE_HISTORY_IDENTITY)) == expected


def test_conflicting_session_cannot_be_later_reverified_or_detached_from_a_result():
    adapter = ClaudeCodeStreamConnector(binary='unused')
    results = []
    adapter._emit = lambda kind, native, payload, **kwargs: results.append(payload) if native == 'result:success' else None

    for operation, started, finished in (
        ('first', NATIVE, NATIVE),
        ('conflicting', NATIVE, OTHER),
        ('later', NATIVE, NATIVE),
    ):
        adapter._append_pending_turn(operation)
        adapter._handle_system({'type': 'system', 'subtype': 'init', 'session_id': started})
        adapter._handle_result({'type': 'result', 'subtype': 'success', 'session_id': finished})
    assert [confirmed_claude_history(value.get(CLAUDE_HISTORY_IDENTITY)) for value in results] == [NATIVE, None, None]


def test_current_history_checks_the_same_owner_after_reading_the_file(monkeypatch):
    adapter = ClaudeCodeStreamConnector(binary='unused')
    session = SimpleNamespace(compatibility_report={'native_version': '2.1.328'})
    adapter._session = session
    adapter._proc = SimpleNamespace(poll=lambda: None)
    adapter._history_state_home = 'approved-home'
    adapter._cwd = 'approved-workspace'
    adapter._emit = lambda *_args, **_kwargs: None

    def finish(operation):
        adapter._append_pending_turn(operation)
        adapter._handle_system({'type': 'system', 'subtype': 'init', 'session_id': NATIVE})
        adapter._handle_result({'type': 'result', 'subtype': 'success', 'session_id': NATIVE})

    def observe(home, native_id, workspace):
        assert (home, native_id, workspace) == ('approved-home', NATIVE, 'approved-workspace')
        return 'fixture-evidence'

    monkeypatch.setattr(claude_code_stream, 'observe_claude_saved_history', observe)
    assert adapter.read_current_owned_saved_history(session) is None
    finish('original')
    assert adapter.read_current_owned_saved_history(session) == 'fixture-evidence'

    def read_during_another_turn(*args):
        finish('later')
        return observe(*args)

    monkeypatch.setattr(claude_code_stream, 'observe_claude_saved_history', read_during_another_turn)
    assert adapter.read_current_owned_saved_history(session) is None


def test_optional_identity_never_overflows_or_reintroduces_redacted_data(monkeypatch):
    payload = {'session_id': NATIVE, 'delivery_outcome': 'success', 'delivery_phase': 'terminal'}
    terminal = RuntimeEvent('server', 'executor', 'session', 'epoch', 1, 'turn_state',
                            'result:success', payload, 'operation')
    fact = {'schema_version': 1, 'session_id': NATIVE}
    limit = len(canonical_json({**payload, CLAUDE_HISTORY_IDENTITY: fact}))
    unchanged = lambda value: value

    monkeypatch.setattr(claude_history_identity, 'MAX_PAYLOAD_BYTES', limit - 1)
    assert claude_history_identity.project_claude_history(terminal, fact, unchanged) is terminal
    monkeypatch.setattr(claude_history_identity, 'MAX_PAYLOAD_BYTES', limit)
    projected = claude_history_identity.project_claude_history(terminal, fact, unchanged)
    assert projected.payload[CLAUDE_HISTORY_IDENTITY] == fact
    assert claude_history_identity.project_claude_history(terminal, fact, lambda _: {}) is terminal
