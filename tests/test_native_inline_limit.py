import pytest

from nexus_connector_core.native.adapter_types import (
    ErrorCode, NativeAdapterError, check_inline_size,
)


def test_native_inline_limit_inclusive_utf8_and_typed_oversize():
    check_inline_size("content", "abcd", 4)
    check_inline_size("content", "é", 2)
    with pytest.raises(NativeAdapterError) as exc:
        check_inline_size("content", "é", 1)
    assert exc.value.code is ErrorCode.CONTENT_TOO_LARGE
    assert exc.value.details == {"field": "content", "max_inline_bytes": 1}
