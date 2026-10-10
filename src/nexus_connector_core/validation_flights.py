"""Share overlapping installation reads, never reuse a completed result.

The producer has its own cancellation scope: cancelling one consumer must
not cancel another session's validation. Producers are bounded and perform
only bounded, read-only installation checks (never spawn or authorize).
"""
from concurrent.futures import ThreadPoolExecutor, TimeoutError
from functools import wraps
from threading import Lock

from .discovery_control import (check_discovery_cancelled, discovery_scope,
                                has_discovery_cancellation_scope)

_workers = ThreadPoolExecutor(max_workers=4, thread_name_prefix="core-validation")
_lock = Lock()
_flights = {}
_MAX_FLIGHTS = 64


def overlapping_validation(function):
    @wraps(function)
    def run(*args, **kwargs):
        check_discovery_cancelled()
        # Passive discovery owns and joins its cancellable readers. Runtime
        # checks have no discovery stop scope and may share overlapping reads.
        if has_discovery_cancellation_scope():
            return function(*args, **kwargs)
        key = (function, tuple(str(arg) for arg in args),
               tuple(sorted((name, str(value)) for name, value in kwargs.items())))
        with _lock:
            for old_key, old_future in tuple(_flights.items()):
                if old_future.done():
                    del _flights[old_key]
            future = _flights.get(key)
            if future is not None and future.done():
                del _flights[key]
                future = None
            if future is None and len(_flights) < _MAX_FLIGHTS:
                def produce():
                    with discovery_scope(None):
                        return function(*args, **kwargs)
                future = _workers.submit(produce)
                _flights[key] = future
        if future is None:
            # Saturation does not grow an unbounded executor queue.
            return function(*args, **kwargs)
        try:
            while True:
                check_discovery_cancelled()
                try:
                    result = future.result(timeout=0.05)
                except TimeoutError:
                    if future.done():
                        return future.result()
                    continue
                check_discovery_cancelled()
                return result
        finally:
            with _lock:
                if future.done() and _flights.get(key) is future:
                    del _flights[key]
    return run
