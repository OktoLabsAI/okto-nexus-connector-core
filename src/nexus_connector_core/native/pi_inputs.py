"""Bounded correlation for Pi RPC dialogs; no I/O or inferred answers."""
from copy import deepcopy
import hashlib
import threading
import time

from ..protocol import canonical_json
from .native_inputs import PI_INPUT, validate_request, response_for


class PiInputRequests:
    def __init__(self):
        self._lock = threading.Lock()
        self._generation = 0
        self._active = False
        self._requests = {}

    def start_turn(self):
        with self._lock:
            self._generation += 1
            self._active = True

    def end_turn(self):
        with self._lock:
            self._active = False
            for entry in self._requests.values():
                entry["pending"] = False

    def capture(self, native):
        identifier = native.get("id")
        if not isinstance(identifier, str) or not 1 <= len(identifier) <= 256:
            return None
        params = {k: v for k, v in native.items() if k not in {"type", "id"}}
        try:
            validate_request(PI_INPUT, params)
            raw = canonical_json([identifier, params])
            if len(raw) > 16000:
                return None
        except (ValueError, TypeError, OverflowError, RecursionError):
            return None
        with self._lock:
            if (not self._active or identifier in self._requests or len(self._requests) >= 256 or
                    sum(e["pending"] for e in self._requests.values()) >= 32):
                return None
            request = dict(schema_version=1, method=PI_INPUT, request_id=identifier,
                params=deepcopy(params), local_generation=self._generation,
                request_hash=hashlib.sha256(raw).hexdigest())
            self._requests[identifier] = dict(request=request, pending=True,
                deadline=time.monotonic() + min((params.get("timeout") or 120000) / 1000, 120))
            return deepcopy(request)

    def owns(self, request):
        if not isinstance(request, dict):
            return False
        with self._lock:
            entry = self._requests.get(request.get("request_id"))
            return bool(entry and entry["pending"] and entry["request"] == request and self._active
                and request["local_generation"] == self._generation and entry["deadline"] > time.monotonic())

    def current(self, request):
        """Also valid after reserving the one response, for the writer fence."""
        with self._lock:
            entry = self._requests.get(request.get("request_id"))
            return bool(entry and {k: v for k, v in entry["request"].items() if k != "schema_version"} ==
                {k: v for k, v in request.items() if k != "schema_version"} and self._active
                and request["local_generation"] == self._generation and entry["deadline"] > time.monotonic())

    def response(self, request, decision):
        with self._lock:
            original = {k: v for k, v in request.items() if k not in {"operator_response", "schema_version"}}
            entry = self._requests.get(request.get("request_id"))
            if (decision not in {"accept", "decline"} or not self._active or not entry or
                    not entry["pending"] or {k: v for k, v in entry["request"].items() if k != "schema_version"} != original or
                    original["local_generation"] != self._generation or entry["deadline"] <= time.monotonic()):
                raise ValueError("Pi question is stale or mismatched")
            response = response_for(entry["request"], request.get("operator_response"), approved=decision == "accept")
            entry["pending"] = False
            return response
