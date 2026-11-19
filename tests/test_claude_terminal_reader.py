import asyncio
from types import SimpleNamespace

from nexus_connector_core.native.claude_terminal_reader import ClaudeTerminalReader
from nexus_connector_core.native.redaction import NativeSecretRedactor


def test_independent_readers_strip_controls_and_mask_secrets_across_native_chunks():
    class Terminal:
        frames = (
            b'\x1b]52;c;clipboard-', b'data\x1b', b'\\\x1b[1;2Hpublic private-', b'\x1b[0mfixture',
            b'-value \x1bPdiscard\x1b\\ retained \xe2', b'\x82\xac\r\n' + b'trailing ' * 12,
        )

        def read_output(self, after, *, timeout):
            assert 0 < timeout <= 1
            if after == len(self.frames):
                return None
            return SimpleNamespace(sequence=after + 1, data=self.frames[after])

    async def observed(reader):
        data = bytearray()
        while (output := await reader.read_output()) is not None:
            data.extend(output)
        return bytes(data)

    async def run():
        terminal = Terminal()
        redactor = NativeSecretRedactor(('private-fixture-value',))
        first = ClaudeTerminalReader(terminal, redactor)
        second = ClaudeTerminalReader(terminal, redactor)
        first_result, second_result = await asyncio.gather(observed(first), observed(second))
        assert first_result == second_result
        assert 'public [REDACTED]  retained €'.encode() in first_result
        assert all(token not in first_result for token in (
            b'private-', b'clipboard-', b'discard', b'\x1b',
        ))

    asyncio.run(run())


def test_idle_reader_releases_short_results_without_leaking_partial_secrets():
    class Terminal:
        def __init__(self):
            self.chunks = iter((b'Answer private-', None, b'fixture-value nxs_', None,
                                b'temporary_token \r\nResult ready.', None))

        def read_output(self, after, *, timeout):
            chunk = next(self.chunks)
            if chunk is None:
                raise TimeoutError
            return SimpleNamespace(sequence=after + 1, data=chunk)

    async def run():
        reader = ClaudeTerminalReader(Terminal(), NativeSecretRedactor(('private-fixture-value',)))
        frames = [await reader.read_output() for _ in range(6)]
        assert frames[1] == b'Answer '
        assert b''.join(frames) == b'Answer [REDACTED] [REDACTED] \r\nResult ready.'
        assert frames[-1].endswith(b'Result ready.')

    asyncio.run(run())
