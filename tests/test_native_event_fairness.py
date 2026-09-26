import pytest

from nexus_connector_core import RuntimeEvent
from nexus_connector_core.native.event_buffers import (
    NativeEventHistory, NativeReplayExpired, event_bytes,
)


def event(session_id, sequence, text="x"):
    return RuntimeEvent("srv", "exe", session_id, "epoch", sequence,
                        "text_delta", "native.output", {"text": text})


def test_noisy_session_evicts_own_replay_before_quiet_session():
    history = NativeEventHistory(max_events=8, max_bytes=100_000,
                                 session_max_events=2,
                                 session_max_bytes=50_000)
    quiet = event("quiet", 1)
    assert history.append(quiet)
    for sequence in range(1, 7):
        assert history.append(event("noisy", sequence))
    assert history.snapshot("quiet") == [quiet]
    with pytest.raises(NativeReplayExpired):
        history.snapshot("noisy")
    assert len(history) == 3


def test_per_session_byte_quota_keeps_quiet_replay():
    quiet = event("quiet", 1, "x" * 20)
    noisy = event("noisy", 1, "x" * 20)
    size = max(event_bytes(quiet), event_bytes(noisy))
    history = NativeEventHistory(max_events=8, max_bytes=size * 6,
                                 session_max_events=8,
                                 session_max_bytes=size * 2)
    assert history.append(quiet)
    for sequence in range(1, 5):
        assert history.append(event("noisy", sequence, "x" * 20))
    assert history.snapshot("quiet") == [quiet]
    assert len(history) == 3


def test_global_byte_pressure_prefers_noisy_sessions_over_quiet_replay():
    quiet = event("quiet", 1)
    sample = event("noisy-a", 1, "x" * 200)
    size = event_bytes(sample)
    history = NativeEventHistory(max_events=100, max_bytes=size * 3,
                                 session_max_events=100,
                                 session_max_bytes=size * 2)
    assert history.append(quiet)
    for session_id in ("noisy-a", "noisy-b"):
        for sequence in (1, 2):
            assert history.append(event(session_id, sequence, "x" * 200))
    assert history.snapshot("quiet") == [quiet]
    assert history._bytes <= history.max_bytes


def test_global_item_pressure_prefers_noisy_sessions_over_quiet_replay():
    history = NativeEventHistory(max_events=4, max_bytes=100_000,
                                 session_max_events=3,
                                 session_max_bytes=50_000)
    quiet = event("quiet", 1)
    assert history.append(quiet)
    for session_id in ("noisy-a", "noisy-b"):
        for sequence in (1, 2, 3):
            assert history.append(event(session_id, sequence))
    assert history.snapshot("quiet") == [quiet]
    assert len(history) <= history.max_events


def test_one_large_new_event_cannot_erase_several_smaller_replays():
    quiet = event("quiet", 1)
    other = event("other", 1)
    large = event("large", 1, "x" * 300)
    limit = event_bytes(quiet) + event_bytes(other) + event_bytes(large) - 1
    history = NativeEventHistory(max_events=100, max_bytes=limit,
                                 session_max_events=100,
                                 session_max_bytes=limit)
    assert history.append(quiet)
    assert history.append(other)
    assert history.append(large) is False
    assert history.snapshot("quiet") == [quiet]
    assert history.snapshot("other") == [other]
    with pytest.raises(NativeReplayExpired):
        history.snapshot("large")


@pytest.mark.parametrize("limits", [
    {"max_events": True}, {"max_bytes": 0},
    {"session_max_events": 0}, {"session_max_bytes": 1.5},
    {"max_events": 2, "session_max_events": 3},
])
def test_history_rejects_invalid_quota_configuration(limits):
    with pytest.raises(ValueError, match="history limits"):
        NativeEventHistory(**limits)
