"""Bounded transient replay and fanout; durable replay belongs to the journal.

Overflow is latched, never a silent queue drop. Readers drain the retained
prefix then receive an explicit gap, allowing the supervisor to record UNKNOWN.
Budgets measure serialized event bytes, not a claim about exact Python RSS.
"""
from collections import OrderedDict, deque
from dataclasses import fields
import json
import queue
import threading


class NativeEventOverflow(RuntimeError):
    def __init__(self):
        super().__init__("native event buffer overflow; outcome unknown")


class NativeReplayExpired(RuntimeError):
    def __init__(self):
        super().__init__("native event replay expired; use canonical durable replay")


class NativeSubscriptionLimit(RuntimeError):
    pass


def event_bytes(event):
    return len(json.dumps({field.name: getattr(event, field.name) for field in fields(event)},
                          ensure_ascii=False, separators=(",", ":")).encode("utf-8"))


class NativeEventHistory:
    def __init__(self, *, max_events=2048, max_bytes=4 * 1024 * 1024,
                 session_max_events=None, session_max_bytes=None):
        if session_max_events is None:
            session_max_events = max_events
        if session_max_bytes is None:
            session_max_bytes = max_bytes
        if (any(type(value) is not int or value < 1 for value in
                (max_events, max_bytes, session_max_events, session_max_bytes)) or
                session_max_events > max_events or session_max_bytes > max_bytes):
            raise ValueError("invalid native history limits")
        self.max_events, self.max_bytes = max_events, max_bytes
        self.session_max_events = session_max_events
        self.session_max_bytes = session_max_bytes
        self._items, self._bytes = OrderedDict(), 0
        self._session_items = {}
        self._session_bytes = {}
        self._next_item_id = 0
        self._expired_sessions = set()
        self._all_expired = False
        self._lock = threading.RLock()

    def _expired(self, session_id):
        if len(self._expired_sessions) < 64:
            self._expired_sessions.add(session_id)
        else:
            self._all_expired = True

    def _remove_oldest_session(self, session_id):
        keys = self._session_items[session_id]
        item_id = keys.popleft()
        old, old_size = self._items.pop(item_id)
        self._bytes -= old_size
        remaining = self._session_bytes[session_id] - old_size
        if keys:
            self._session_bytes[session_id] = remaining
        else:
            del self._session_items[session_id]
            del self._session_bytes[session_id]
        self._expired(old.session_id)

    def _remove_oldest_global(self, *, by_bytes, incoming_session_id):
        # Keep a quiet session's small replay window when several noisy
        # sessions together exhaust the shared budget. The oldest item of
        # the largest holder is discarded, preserving order within each
        # session and latching an explicit gap for that holder. This scan is
        # bounded by max_events (and runs only at global pressure).
        holder = max(
            self._session_items,
            key=lambda session_id: (
                self._session_bytes[session_id] if by_bytes
                else len(self._session_items[session_id]),
                session_id == incoming_session_id,
            ),
        )
        self._remove_oldest_session(holder)

    def append(self, event):
        size = event_bytes(event)
        with self._lock:
            if size > self.max_bytes or size > self.session_max_bytes:
                self._expired(event.session_id)
                return False
            while (self._session_items.get(event.session_id) and
                   (len(self._session_items[event.session_id]) >= self.session_max_events or
                    self._session_bytes[event.session_id] + size > self.session_max_bytes)):
                self._remove_oldest_session(event.session_id)
            if (self._items and self._bytes + size > self.max_bytes and
                    size > max(self._session_bytes.values())):
                # One large incoming frame must not erase several quieter
                # sessions merely to create a transient replay entry. Live
                # fanout still receives it; only this session's replay is
                # explicitly expired. Decide before any global eviction.
                self._expired(event.session_id)
                return False
            while self._items and (len(self._items) >= self.max_events or self._bytes + size > self.max_bytes):
                self._remove_oldest_global(
                    by_bytes=self._bytes + size > self.max_bytes,
                    incoming_session_id=event.session_id)
            item_id = self._next_item_id
            self._next_item_id += 1
            self._items[item_id] = (event, size)
            self._session_items.setdefault(event.session_id, deque()).append(item_id)
            self._session_bytes[event.session_id] = self._session_bytes.get(event.session_id, 0) + size
            self._bytes += size
            return True

    def snapshot(self, session_id=None):
        with self._lock:
            if self._all_expired or (bool(self._expired_sessions) if session_id is None
                                     else session_id in self._expired_sessions):
                raise NativeReplayExpired()
            return [event for event, _ in self._items.values()
                    if session_id is None or event.session_id == session_id]

    def __iter__(self):
        return iter(self.snapshot())

    def __len__(self):
        with self._lock:
            return len(self._items)


class NativeEventQueue:
    def __init__(self, *, max_events=128, max_bytes=2 * 1024 * 1024, coalesce=None):
        self.max_events, self.max_bytes = max_events, max_bytes
        self.coalesce = coalesce
        self._items, self._bytes = deque(), 0
        self._overflow = False
        self._changed = threading.Condition()

    def put(self, event):
        size = event_bytes(event)
        with self._changed:
            coalesce = self.coalesce
            if not self._overflow and self._items and coalesce is not None:
                previous, previous_size = self._items[-1]
                merged = coalesce(previous, event)
                if merged is not None:
                    merged_size = event_bytes(merged)
                    if self._bytes - previous_size + merged_size <= self.max_bytes:
                        self._items[-1] = (merged, merged_size)
                        self._bytes += merged_size - previous_size
                        self._changed.notify()
                        return True
            if self._overflow or len(self._items) >= self.max_events or self._bytes + size > self.max_bytes:
                self._overflow = True
                self._changed.notify_all()
                return False
            self._items.append((event, size))
            self._bytes += size
            self._changed.notify()
            return True

    def get(self, timeout=None):
        with self._changed:
            if not self._changed.wait_for(lambda: self._items or self._overflow, timeout):
                raise queue.Empty
            if self._items:
                event, size = self._items.popleft()
                self._bytes -= size
                return event
            raise NativeEventOverflow()

    def qsize(self):
        with self._changed:
            return len(self._items)


def subscribe(history, subscribers, *, session_id=None, coalesce=None):
    """Caller holds its append/snapshot registration lock."""
    if len(subscribers) >= 16:
        raise NativeSubscriptionLimit("native event subscription capacity exhausted")
    backlog = history.snapshot(session_id)
    subscriber = NativeEventQueue(coalesce=coalesce)
    subscribers.append(subscriber)
    return subscriber, backlog


def stop_overflowed_process(process):
    # Never used by attach; only an actual owned Popen object is accepted here.
    if process is not None:
        try:
            if process.poll() is None:
                process.kill()
        except OSError:
            pass  # Queue gap and lifecycle observation still report uncertainty.
