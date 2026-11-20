import asyncio
from types import SimpleNamespace

import pytest

from nexus_connector_core import CoreError
from nexus_connector_core.native.claude_terminal_reader import ClaudeTerminalReader, ClaudeTerminalText
from nexus_connector_core.native.process import windows_terminal
from nexus_connector_core.native.redaction import NativeSecretRedactor


def test_independent_readers_strip_controls_and_mask_secrets_across_native_chunks():
    frames = (
        b'\x1b]52;c;clipboard-', b'data\x1b', b'\\\x1b[1;2Hpublic private-', b'\x1b[0mfixture',
        b'-value \x1bPdiscard\x1b\\ retained \xe2', b'\x82\xac\r\n' + b'trailing ' * 12,
    )
    replay = windows_terminal._OutputReplay(ClaudeTerminalText(NativeSecretRedactor(('private-fixture-value',))))
    for frame in frames:
        replay.append(frame)
    replay.end(failed=False)

    async def observed(reader):
        data = bytearray()
        while (output := await reader.read_output()) is not None:
            data.extend(output)
        return bytes(data)

    async def run():
        terminal = SimpleNamespace(read_output=replay.read)
        first = ClaudeTerminalReader(terminal)
        second = ClaudeTerminalReader(terminal)
        first_result, second_result = await asyncio.gather(observed(first), observed(second))
        assert first_result == second_result
        assert 'public [REDACTED]  retained €'.encode() in first_result
        assert all(token not in first_result for token in (
            b'private-', b'clipboard-', b'discard', b'\x1b',
        ))

    asyncio.run(run())


def test_idle_reader_releases_short_results_without_leaking_partial_secrets():
    replay = windows_terminal._OutputReplay(ClaudeTerminalText(NativeSecretRedactor(('private-fixture-value',))))
    terminal = SimpleNamespace(read_output=lambda after, *, timeout: replay.read(after, timeout=0))

    async def run():
        reader = ClaudeTerminalReader(terminal)
        replay.append(b'Answer private-')
        assert await reader.read_output() == b'Answer '
        replay.append(b'fixture-value nxs_')
        assert await reader.read_output() == b'[REDACTED] '
        replay.append(b'temporary_token \r\nResult ready.')
        assert await reader.read_output() == b'[REDACTED] \r\nResult ready.'

    asyncio.run(run())


def test_projection_failure_retires_the_display_without_refusing_terminal_output():
    replay = windows_terminal._OutputReplay(ClaudeTerminalText(NativeSecretRedactor()))
    replay.append(b'Visible text\n' + b'nxs_' + b'x' * 4096)
    for _ in range(6):
        replay.append(b'x' * 4096)
    with pytest.raises(CoreError, match='NATIVE_UNAVAILABLE'):
        replay.read(0, timeout=0)
    replay.append(b'additional owner output after the presentation failed')
    replay.end(failed=False)
    with pytest.raises(CoreError, match='NATIVE_UNAVAILABLE'):
        replay.read(0, timeout=0)


def test_new_reader_after_eviction_opens_only_retained_safe_text(monkeypatch):
    monkeypatch.setattr(windows_terminal, '_REPLAY_BYTES', 120)
    replay = windows_terminal._OutputReplay(ClaudeTerminalText(NativeSecretRedactor(('private-fixture-value',))))
    terminal = SimpleNamespace(read_output=replay.read)

    async def run():
        slow = ClaudeTerminalReader(terminal)
        replay.append(b'Old output ' * 7)
        assert b'Old output' in await slow.read_output()
        for chunk in (b'Later output ' * 6, b'Last full redraw ' * 5 + b'\x1b]52;c;opaque-',
                      b'clipboard-control\x1b\\\r\nprivate-', b'fixture-value \xe2',
                      b'\x82\xac result ready.'):
            replay.append(chunk)
        replay.end(failed=False)
        with pytest.raises(CoreError, match='SESSION_CONFLICT'):
            await slow.read_output()
        fresh = ClaudeTerminalReader(terminal)
        frames = [first := await fresh.read_output()]
        while (frame := await fresh.read_output()) is not None:
            frames.append(frame)
        assert first.startswith(b'[Earlier Claude terminal output is no longer available.]')
        retained = b''.join(frames)
        assert '[REDACTED] € result ready.'.encode() in retained
        assert all(part not in retained for part in (b'private-', b'fixture-value', b'clipboard-control', b'\x1b'))

    asyncio.run(run())
