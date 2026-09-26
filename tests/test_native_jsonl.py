import pytest

from nexus_connector_core.native.jsonl import JSONLDecoder


def test_fragmented_utf8_crlf_and_unicode_internal():
    decoder = JSONLDecoder()
    data = '{"text":"á\u2028b\u2029c"}\r\n{"id":2}\n'.encode("utf-8")
    frames = []
    for byte in data:
        frames.extend(decoder.feed(bytes([byte])))
    decoder.finish()
    assert frames == [{"text": "á\u2028b\u2029c"}, {"id": 2}]


def test_limit_and_duplicate_key_fail_closed():
    decoder = JSONLDecoder(max_frame_bytes=8)
    with pytest.raises(ValueError, match="byte limit"):
        decoder.feed(b"x" * 9)
    with pytest.raises(RuntimeError, match="closed"):
        decoder.feed(b"\n")
    with pytest.raises(ValueError, match="duplicate"):
        JSONLDecoder().feed(b'{"x":1,"x":2}\n')


def test_incomplete_final_frame_is_error():
    decoder = JSONLDecoder()
    decoder.feed(b'{"a":1}')
    with pytest.raises(ValueError, match="incomplete"):
        decoder.finish()


@pytest.mark.parametrize("limit", [True, 1.5, "8", 0, 1024 * 1024 + 1])
def test_invalid_byte_limit_is_rejected_before_feed(limit):
    with pytest.raises(ValueError, match="limit"):
        JSONLDecoder(max_frame_bytes=limit)


def test_feed_bounds_chunk_and_returned_record_count():
    decoder = JSONLDecoder()
    with pytest.raises(TypeError, match="bytes"):
        decoder.feed("{}\n")
    assert decoder.feed(b"{}\n") == [{}]

    too_many = JSONLDecoder()
    with pytest.raises(ValueError, match="record limit"):
        too_many.feed(b"{}\n" * 1025)
    with pytest.raises(RuntimeError, match="closed"):
        too_many.feed(b"{}\n")

    oversized = JSONLDecoder(max_frame_bytes=4)
    with pytest.raises(ValueError, match="byte limit"):
        oversized.feed(b"{}\n{}\n")
    with pytest.raises(RuntimeError, match="closed"):
        oversized.feed(b"{}\n")


@pytest.mark.parametrize("line", [b'{"x":"\\ud800"}\n',
                                  b'{"x":9007199254740992}\n'])
def test_non_interoperable_json_is_rejected_and_decoder_closes(line):
    decoder = JSONLDecoder()
    with pytest.raises(ValueError):
        decoder.feed(line)
    with pytest.raises(RuntimeError, match="closed"):
        decoder.feed(b'{}\n')
