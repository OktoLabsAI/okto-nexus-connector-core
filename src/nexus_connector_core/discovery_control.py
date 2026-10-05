"""Cooperative interruption of passive discovery reads only."""
from contextlib import contextmanager
from contextvars import ContextVar


class DiscoveryCancelled(Exception):
    """The host stopped passive observation before receiving an inventory."""


_cancel_requested = ContextVar("discovery_cancel_requested", default=None)


def check_discovery_cancelled():
    callback = _cancel_requested.get()
    if callback is not None and callback():
        raise DiscoveryCancelled("Passive discovery was stopped.")


@contextmanager
def discovery_scope(cancel_requested):
    if cancel_requested is not None and not callable(cancel_requested):
        raise TypeError("cancel_requested must be callable or None")
    token = _cancel_requested.set(cancel_requested)
    try:
        check_discovery_cancelled()
        yield
        check_discovery_cancelled()
    finally:
        _cancel_requested.reset(token)
