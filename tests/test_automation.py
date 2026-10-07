import asyncio

import pytest

from nexus_connector_core import DEFAULT_RUNTIME_AUTOMATION, RuntimeAutomation, RuntimeAutomationPolicy


def test_defaults_enable_messages_and_recovery():
    assert DEFAULT_RUNTIME_AUTOMATION.automatic_messages
    assert DEFAULT_RUNTIME_AUTOMATION.automatic_recovery
    assert DEFAULT_RUNTIME_AUTOMATION.recovery_attempts == 5


@pytest.mark.parametrize('changes', [dict(recovery_attempts=True), dict(retry_delays=()),
    dict(retry_delays=(float('nan'),)), dict(message_interval=0), dict(automatic_recovery=1),
    dict(stable_seconds=0), dict(retry_jitter=1), dict(retry_jitter=-0.1)])
def test_invalid_policy(changes):
    with pytest.raises(ValueError):
        RuntimeAutomationPolicy(**changes)


def test_recovery_retries_proofs_and_drains_only_host_pending_work():
    async def run():
        stop, events, delays = asyncio.Event(), [], []
        async def pause(delay): delays.append(delay)
        async def pending(): events.append('pending')
        async def attempt():
            events.append('proof')
            return events.count('proof') == 3
        assert await RuntimeAutomation().recover(attempt=attempt, pending=pending, stop=stop, wait=pause)
        assert delays == [2, 4, 8]
        assert events == ['pending', 'proof'] * 3
    asyncio.run(run())


def test_continuous_recovery_observes_late_resolution_without_operator_action():
    async def scenario():
        stop = asyncio.Event()
        attempts, delays = [], []
        async def attempt():
            attempts.append(True)
            return len(attempts) == 7
        async def pause(delay):
            delays.append(delay)
        assert await RuntimeAutomation().recover(attempt=attempt, stop=stop, wait=pause, continuous=True)
        assert len(attempts) == 7
        assert delays[-3:] == [30, 30, 30]
    asyncio.run(scenario())


def test_exhaustion_preserves_independent_deliveries_without_extra_attempts():
    async def run():
        stop, attempts, pending_count, notices = asyncio.Event(), 0, 0, 0
        async def pause(_): pass
        async def attempt():
            nonlocal attempts
            attempts += 1
            return False
        async def pending():
            nonlocal pending_count
            pending_count += 1
        async def exhausted():
            nonlocal notices
            notices += 1
            if notices == 2: stop.set()
        assert not await RuntimeAutomation().recover(attempt=attempt, pending=pending,
            exhausted=exhausted, stop=stop, wait=pause)
        assert (attempts, pending_count) == (5, 6)
    asyncio.run(run())


def test_reenable_opens_new_budget_and_stop_does_not_start_work():
    async def run():
        stop, active, attempts = asyncio.Event(), True, 0
        async def enabled(): return active
        async def attempt():
            nonlocal attempts
            attempts += 1
            return attempts == 2
        async def exhausted():
            nonlocal active
            active = False
        async def pause(_):
            nonlocal active
            if not active:
                # Allow one disabled observation before enabling again.
                if getattr(pause, 'observed', False): active = True
                else: pause.observed = True
        runner = RuntimeAutomation(RuntimeAutomationPolicy(recovery_attempts=1))
        assert await runner.recover(attempt=attempt, stop=stop, enabled=enabled, exhausted=exhausted, wait=pause)
        stop.set()
        assert not await runner.recover(attempt=attempt, stop=stop, wait=pause)
        assert attempts == 2
    asyncio.run(run())


def test_connector_retries_network_and_reconciliation_until_stopped():
    async def run():
        stop, calls, delays = asyncio.Event(), 0, []
        async def cycle():
            nonlocal calls
            calls += 1
            if calls == 20:
                stop.set()
            raise RuntimeError('network' if calls <= 7 else 'recovery')
        async def failed(error): return str(error) == 'recovery'
        async def exhausted(): raise AssertionError('Connection retries must not exhaust')
        async def pause(delay): delays.append(delay)
        await RuntimeAutomation().supervise_connection(cycle=cycle, stop=stop,
            failed=failed, exhausted=exhausted, wait=pause)
        assert calls == 20 and delays == [2, 4, 8, 16] + [30] * 15
    asyncio.run(run())


def test_shutdown_joins_callback_without_replaying_it():
    async def run():
        stop, entered, released, effects = asyncio.Event(), asyncio.Event(), asyncio.Event(), []
        async def pause(_): pass
        async def cycle():
            entered.set()
            await released.wait()
            effects.append('once')
        async def failed(_): raise AssertionError('Unexpected failure')
        async def exhausted(): raise AssertionError('Unexpected exhaustion')
        task = asyncio.create_task(RuntimeAutomation().supervise_connection(cycle=cycle,
            stop=stop, failed=failed, exhausted=exhausted, wait=pause))
        await entered.wait()
        stop.set()
        assert not task.done()
        released.set()
        await task
        assert effects == ['once']
    asyncio.run(run())


def test_shutdown_during_pending_delivery_prevents_new_reconciliation():
    async def run():
        stop = asyncio.Event()
        async def pause(_): pass
        async def pending(): stop.set()
        async def attempt(): raise AssertionError('Stopped hosts must not start new recovery.')
        assert not await RuntimeAutomation().recover(attempt=attempt, pending=pending, stop=stop, wait=pause)
    asyncio.run(run())


def test_stable_connection_restarts_backoff():
    async def run():
        stop, delays, time = asyncio.Event(), [], [0.0]
        # Three quick failures, one connection that stayed up, then quick again.
        durations = iter([0, 0, 0, 120, 0, 0])
        async def cycle():
            time[0] += next(durations)
            if len(delays) == 5:
                stop.set()
            raise RuntimeError('network')
        async def failed(error): return False
        async def exhausted(): raise AssertionError('Connection retries must not exhaust')
        async def pause(delay): delays.append(delay)
        await RuntimeAutomation().supervise_connection(cycle=cycle, stop=stop,
            failed=failed, exhausted=exhausted, wait=pause, clock=lambda: time[0])
        assert delays == [2, 4, 8, 2, 4]
    asyncio.run(run())


def test_reconnect_jitter_is_bounded_and_off_by_default():
    assert RuntimeAutomationPolicy().reconnect_delay(5, rand=lambda: 0.0) == 30
    policy = RuntimeAutomationPolicy(retry_jitter=0.2)
    assert policy.reconnect_delay(1, rand=lambda: 0.0) == pytest.approx(1.6)
    assert policy.reconnect_delay(1, rand=lambda: 1.0) == pytest.approx(2.4)
    assert policy.reconnect_delay(5, rand=lambda: 0.5) == pytest.approx(30)
