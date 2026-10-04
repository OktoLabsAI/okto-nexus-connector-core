import asyncio

import pytest

from nexus_connector_core import DEFAULT_RUNTIME_AUTOMATION, RuntimeAutomation, RuntimeAutomationPolicy


def test_defaults_enable_messages_and_recovery():
    assert DEFAULT_RUNTIME_AUTOMATION.automatic_messages
    assert DEFAULT_RUNTIME_AUTOMATION.automatic_recovery
    assert DEFAULT_RUNTIME_AUTOMATION.recovery_attempts == 5


@pytest.mark.parametrize('changes', [dict(recovery_attempts=True), dict(retry_delays=()),
    dict(retry_delays=(float('nan'),)), dict(message_interval=0), dict(automatic_recovery=1)])
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


def test_connector_network_reconnects_and_reconciliation_have_separate_budgets():
    async def run():
        stop, calls, delays = asyncio.Event(), 0, []
        async def cycle():
            nonlocal calls
            calls += 1
            raise RuntimeError('network' if calls <= 7 else 'recovery')
        async def failed(error): return str(error) == 'recovery'
        async def exhausted(): stop.set()
        async def pause(delay): delays.append(delay)
        await RuntimeAutomation().supervise_connection(cycle=cycle, stop=stop,
            failed=failed, exhausted=exhausted, wait=pause)
        assert calls == 12 and max(delays) == 30
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
