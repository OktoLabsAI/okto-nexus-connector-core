
import json, os, sys, time

scenario = os.environ.get("FAKE_CC_SCENARIO", "basic")
session_id = "fake-native-session-id"
generating = False

def emit(obj):
    sys.stdout.write(json.dumps(obj) + "\n")
    sys.stdout.flush()

# One raw-fd reader and a bounded line queue work on Windows and POSIX.
# select() on Windows accepts sockets, not subprocess stdin pipes. Keeping
# one reader also prevents buffered-read/select disagreements on POSIX.
import queue, threading, codecs
_lines = queue.Queue(maxsize=128)
_stdin_eof = False

def _read_stdin():
    decoder = codecs.getincrementaldecoder("utf-8")()
    pending = ""
    while True:
        chunk = os.read(0, 65536)
        if not chunk:
            pending += decoder.decode(b"", final=True)
            if pending:
                _lines.put(pending)
            _lines.put("")
            return
        pending += decoder.decode(chunk)
        while "\n" in pending:
            line, pending = pending.split("\n", 1)
            _lines.put(line + "\n")

threading.Thread(target=_read_stdin, daemon=True).start()

def read_line_blocking():
    global _stdin_eof
    if _stdin_eof:
        return ""
    line = _lines.get()
    _stdin_eof = line == ""
    return line

def read_line_within(timeout_s):
    global _stdin_eof
    if _stdin_eof:
        return ""
    try:
        line = _lines.get(timeout=timeout_s)
    except queue.Empty:
        return None
    _stdin_eof = line == ""
    return line

if scenario == "garbage_line":
    sys.stdout.write("not json at all\n")
    sys.stdout.flush()

if scenario == "die_without_result":
    # Consume nothing useful; die as soon as any input arrives.
    read_line_blocking()
    sys.stderr.write("simulated abrupt death\n")
    sys.stderr.flush()
    sys.exit(2)

if scenario == "eof_without_exit":
    # Consume the turn, then close BOTH streams at the raw OS fd level
    # (both reader threads hit genuine EOF - _finish() runs) but never
    # actually exit the process: sleeps far past _EXIT_WAIT_TIMEOUT_S with
    # stdin left open. This is what `_finish`'s proc.wait(timeout=...) is a
    # backstop against. NOTE: `sys.stdout.close()`/`sys.stderr.close()`
    # (the TextIOWrapper level) do NOT reliably release the pipe's write
    # end promptly on every platform - verified empirically (macOS/CPython
    # 3.13: EOF was NOT observed by the parent until full process exit).
    # `os.close(fd)` on the raw fd does.
    read_line_blocking()
    sys.stdout.flush()
    sys.stderr.flush()
    os.close(1)
    os.close(2)
    time.sleep(30)
    os._exit(0)  # never reached within the test's own bound

def handle_control_request(msg):
    # Answers a control_request; returns True iff it was an honoured interrupt.
    req = msg.get("request") or {}
    req_id = msg.get("request_id")
    subtype = req.get("subtype")
    if subtype == "interrupt":
        if scenario == "crash_early_interrupt" and not generating:
            emit({"type": "control_response", "response": {"subtype": "success", "request_id": req_id, "response": {"still_queued": []}}})
            emit({"type": "result", "subtype": "error_during_execution", "session_id": session_id, "result": ""})
            sys.exit(1)
        emit({"type": "control_response", "response": {"subtype": "success", "request_id": req_id, "response": {"still_queued": []}}})
        emit({"type": "result", "subtype": "error_during_execution", "session_id": session_id, "result": ""})
        return True
    emit({"type": "control_response", "response": {"subtype": "error", "request_id": req_id, "error": "Unsupported control request subtype: " + str(subtype)}})
    return False

deferred_lines = []  # lines read-but-not-consumed by the mid-generation select loop below

def next_raw_line():
    if deferred_lines:
        return deferred_lines.pop(0)
    return read_line_blocking()

while True:
    raw = next_raw_line()
    if raw == "":
        break  # EOF - stdin closed, matches `for raw in sys.stdin`'s natural end
    raw = raw.strip()
    if not raw:
        continue
    try:
        msg = json.loads(raw)
    except json.JSONDecodeError:
        sys.stderr.write("Error parsing streaming input line\n")
        sys.stderr.flush()
        sys.exit(1)

    mtype = msg.get("type")

    if mtype == "control_request":
        generating = False
        handle_control_request(msg)
        continue

    if mtype != "user":
        # Unknown top-level type: silently ignored, matching the real CLI.
        continue

    content = (msg.get("message") or {}).get("content")
    if content is None:
        sys.stderr.write("Error: Expected message role 'user', got 'undefined'\n")
        sys.exit(1)

    emit({"type": "system", "subtype": "init", "session_id": session_id})
    generating = False
    if scenario == "slow_start":
        time.sleep(0.5)
    generating = True
    emit({"type": "stream_event", "event": {"type": "message_start"}})
    emit({"type": "stream_event", "event": {"type": "content_block_start"}})

    interrupted = False
    if scenario == "slow_start":
        # A real generating WINDOW (not just a delay before it): poll stdin
        # with select for up to ~2s so a control_request sent while this
        # turn is "in flight" has a genuine chance to land mid-turn and be
        # honoured inline - mirroring the real CLI's documented behaviour
        # (control_request answered synchronously during an in-flight turn,
        # module docstring) - rather than only ever being visible on the
        # NEXT top-level `for raw in sys.stdin` iteration, which would make
        # a mid-generation interrupt structurally impossible to simulate.
        deadline = time.monotonic() + 2.0
        while time.monotonic() < deadline:
            raw2 = read_line_within(0.05)
            if raw2 is None:
                continue
            if raw2 == "":
                sys.exit(0)  # stdin closed mid-generation: exit like the real CLI's clean path.
            raw2 = raw2.strip()
            if not raw2:
                continue
            try:
                msg2 = json.loads(raw2)
            except json.JSONDecodeError:
                sys.stderr.write("Error parsing streaming input line\n")
                sys.exit(1)
            if msg2.get("type") == "control_request":
                if handle_control_request(msg2):
                    interrupted = True
                    generating = False
                break
            # Any other top-level type arriving mid-generation (e.g. an
            # ordinary queued send_turn racing an interrupt): the real CLI
            # strictly defers it to run AFTER the current turn (module
            # docstring) - DEFER it back into the main read loop (via
            # `deferred_lines`) rather than dropping it, so a test can
            # exercise ">1 turn genuinely outstanding" without losing the
            # second turn's content.
            deferred_lines.append(raw2)

    if not interrupted:
        text = "echo:" + str(content)
        if scenario == "strict_json_hostile":
            sys.stdout.write('{"type":"result","type":"system"}\n')
            sys.stdout.write('{"type":"result","value":NaN}\n')
            sys.stdout.write('{"type":"result","value":"\\ud800"}\n')
            sys.stdout.write('{"type":"result","value":9007199254740992}\n')
            sys.stdout.flush()
        if scenario == "shape_drifted_mid_turn":
            emit({"type": "stream_event", "event": "oops"})
        emit({"type": "stream_event", "event": {"type": "content_block_delta", "index": 0, "delta": {"type": "text_delta", "text": text}}})
        emit({"type": "assistant", "message": {"role": "assistant", "content": [{"type": "text", "text": text}]}})
        emit({"type": "stream_event", "event": {"type": "content_block_stop"}})
        emit({"type": "result", "subtype": "success", "session_id": session_id, "result": text})
        generating = False

sys.exit(0)
