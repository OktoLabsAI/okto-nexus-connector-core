
import json
import os
import sys
import threading
import time

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else None
_write_lock = threading.Lock()
_log_lock = threading.Lock()
_ui_counter = 0
_state_lock = threading.Lock()
_pending_steer = []
_abort_requested = threading.Event()
_die_on_abort = threading.Event()
_reject_abort = threading.Event()
NO_ACK_GET_STATE = len(sys.argv) > 2 and sys.argv[2] == "NO_ACK_GET_STATE"
LATE_ACK_GET_STATE = len(sys.argv) > 2 and sys.argv[2] == "LATE_ACK_GET_STATE"
# Real pi wire order (protocol reference section 6(b)): agent_settled for the
# ABORTED turn arrives BEFORE response(abort, success:true) - the ack is not
# the safe-to-reprompt signal, agent_settled is. This flag/lock pair defers
# the abort ack until the aborted turn has actually finished settling,
# instead of answering it the instant the abort command is read (which is
# the wrong order and was the fake server's own bug - see C1).
_abort_response_lock = threading.Lock()
_abort_response_owed = False


def _send_abort_response_once():
    global _abort_response_owed
    with _abort_response_lock:
        if not _abort_response_owed:
            return
        _abort_response_owed = False
    write_msg({"type": "response", "command": "abort", "success": True})


def write_line(text):
    with _write_lock:
        sys.stdout.write(text + "\n")
        sys.stdout.flush()


def write_msg(obj):
    write_line(json.dumps(obj))


def log(entry):
    if not LOG_PATH:
        return
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def next_ui_id():
    global _ui_counter
    _ui_counter += 1
    return "ui_%d" % _ui_counter


def emit_startup_noise():
    for _ in range(7):
        write_msg({"type": "extension_ui_request", "id": next_ui_id(), "method": "setStatus", "statusKey": "statusline"})


def handle_turn(text):
    _abort_requested.clear()
    write_msg({"type": "agent_start"})
    write_msg({"type": "turn_start"})
    write_msg({"type": "message_start", "role": "user"})
    write_msg({"type": "message_end", "role": "user"})

    if "TRIGGER_MALFORMED" in text:
        write_line("not-json-garbage-from-pi")

    if "TRIGGER_HOSTILE_JSON" in text:
        write_line('{"type":"agent_end","type":"turn_end"}')
        write_line('{"type":"agent_end","value":NaN}')
        write_line('{"type":"agent_end","value":"\\ud800"}')
        write_line('{"type":"agent_end","value":9007199254740992}')

    if "TRIGGER_BYTE_FRAMING" in text:
        framed = '{"type":"native_utf8_probe","text":"á\u2028b\u2029c"}\r\n'.encode("utf-8")
        split = framed.index(b"\xc3") + 1
        with _write_lock:
            sys.stdout.buffer.write(framed[:split])
            sys.stdout.buffer.flush()
            time.sleep(0.01)
            sys.stdout.buffer.write(framed[split:])
            sys.stdout.buffer.write(b'{"type":"native_bad","text":"\xff"}\n')
            sys.stdout.buffer.flush()

    if "TRIGGER_DEEPNEST" in text:
        # Syntactically VALID JSON (a balanced, deeply nested array) - NOT a
        # json.JSONDecodeError. json.loads() itself raises RecursionError
        # parsing it (Python's C/Python JSON decoder recurses per nesting
        # level), which `except json.JSONDecodeError` in
        # `_PiTransport._read_stdout` does NOT catch (RecursionError is not
        # a ValueError subclass). See RES-B1 in the evidence file for the
        # empirically confirmed consequence.
        _depth = 20000
        write_line("[" * _depth + "]" * _depth)

    if "TRIGGER_SPURIOUS_RESPONSE" in text:
        write_msg({"type": "response", "command": "get_session_stats", "success": True, "data": {}})

    if "TRIGGER_CRASH" in text:
        write_msg({"type": "message_start", "role": "assistant"})
        time.sleep(0.05)
        os._exit(7)

    if "TRIGGER_HOLD_FOR_STEER" in text:
        write_msg({"type": "tool_execution_start", "toolCallId": "tc1", "toolName": "bash"})
        deadline = time.time() + 5.0
        while time.time() < deadline:
            with _state_lock:
                steer_pending = list(_pending_steer)
            if steer_pending:
                break
            time.sleep(0.02)
        write_msg({"type": "tool_execution_end", "toolCallId": "tc1", "isError": False, "result": "done"})
        write_msg({"type": "turn_end"})
        write_msg({"type": "turn_start"})
        with _state_lock:
            drained = list(_pending_steer)
            _pending_steer.clear()
        write_msg({"type": "queue_update", "steering": [], "followUp": []})
        for _steer_text in drained:
            write_msg({"type": "message_start", "role": "user"})
            write_msg({"type": "message_end", "role": "user"})
        write_msg({"type": "message_start", "role": "assistant"})
        write_msg({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": "steered-ok"}})
        write_msg({"type": "message_end", "role": "assistant", "stopReason": "stop"})
        write_msg({"type": "turn_end"})
        write_msg({"type": "agent_end"})
        write_msg({"type": "agent_settled"})
        return

    if "TRIGGER_DIE_ON_ABORT" in text:
        write_msg({"type": "tool_execution_start", "toolCallId": "tc3", "toolName": "bash"})
        _die_on_abort.set()
        time.sleep(5.0)
        return

    if "TRIGGER_HOLD_FOR_ABORT" in text:
        write_msg({"type": "tool_execution_start", "toolCallId": "tc2", "toolName": "bash"})
        deadline = time.time() + 5.0
        while time.time() < deadline and not _abort_requested.is_set():
            time.sleep(0.02)
        if _abort_requested.is_set():
            # Deterministic window (real pi: ~17-30ms per the protocol
            # reference's measured abort-mid-tool-call case) between the
            # abort write landing and the aborted turn actually finishing -
            # gives C1's race-window test something reliable to hit instead
            # of a few-ms window inherent in the fast path below.
            time.sleep(0.3)
            write_msg({"type": "tool_execution_end", "toolCallId": "tc2", "isError": True, "result": "Operation aborted"})
            write_msg({"type": "turn_end"})
            write_msg({"type": "message_start", "role": "assistant"})
            write_msg({"type": "message_end", "role": "assistant", "stopReason": "error"})
            write_msg({"type": "turn_end"})
            write_msg({"type": "agent_end"})
            write_msg({"type": "agent_settled"})
            # Real order (protocol reference 6(b)): agent_settled for the
            # ABORTED turn arrives BEFORE response(abort,success:true).
            _send_abort_response_once()
            return
        write_msg({"type": "tool_execution_end", "toolCallId": "tc2", "isError": False, "result": "done"})
        write_msg({"type": "turn_end"})
        write_msg({"type": "message_start", "role": "assistant"})
        write_msg({"type": "message_end", "role": "assistant", "stopReason": "stop"})
        write_msg({"type": "turn_end"})
        write_msg({"type": "agent_end"})
        write_msg({"type": "agent_settled"})
        return

    write_msg({"type": "message_start", "role": "assistant"})
    write_msg({"type": "message_update", "assistantMessageEvent": {"type": "text_delta", "delta": text}})
    write_msg({"type": "message_end", "role": "assistant", "stopReason": "stop"})
    write_msg({"type": "turn_end"})
    write_msg({"type": "agent_end"})
    write_msg({"type": "agent_settled"})


def main():
    emit_startup_noise()
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            write_msg({"type": "response", "command": "parse", "success": False, "error": "bad json"})
            continue
        log({"recv": msg})
        verb = msg.get("type")
        if verb == "get_state":
            if NO_ACK_GET_STATE:
                continue  # deliberately never answer - for the C3 handshake-timeout test
            if LATE_ACK_GET_STATE:
                def late_ack():
                    time.sleep(0.2)
                    write_msg({"type": "response", "command": "get_state", "success": True,
                               "data": {"sessionId": "late"}})
                threading.Thread(target=late_ack, daemon=True).start()
                continue
            write_msg({"type": "response", "command": "get_state", "success": True, "data": {"sessionId": "fake"}})
        elif verb == "extension_ui_response":
            continue
        elif verb == "prompt":
            text = msg.get("message", "")
            if "TRIGGER_ERROR" in text:
                write_msg({"type": "response", "command": "prompt", "success": False, "error": "rejected"})
                continue
            if "TRIGGER_REJECT_ABORT" in text:
                _reject_abort.set()
            write_msg({"type": "response", "command": "prompt", "success": True})
            if "TRIGGER_STALE_SETTLED_BEFORE_START" in text:
                # An old ID-less terminal arrives before this prompt's start.
                write_msg({"type": "agent_settled"})
                time.sleep(0.05)
            threading.Thread(target=handle_turn, args=(text,), daemon=True).start()
        elif verb == "steer":
            text = msg.get("message", "")
            if "TRIGGER_REJECT_STEER" in text:
                write_msg({"type": "response", "command": "steer", "success": False,
                           "error": "rejected"})
                continue
            with _state_lock:
                _pending_steer.append(text)
            write_msg({"type": "response", "command": "steer", "success": True})
            write_msg({"type": "queue_update", "steering": list(_pending_steer), "followUp": []})
        elif verb == "abort":
            if _die_on_abort.is_set():
                os._exit(9)
            if _reject_abort.is_set():
                write_msg({"type": "response", "command": "abort", "success": False,
                           "error": "rejected"})
                continue
            global _abort_response_owed
            with _abort_response_lock:
                _abort_response_owed = True
            _abort_requested.set()
            # NOTE: protocol case (a) (abort with nothing in flight, which
            # settles - and therefore acks - in ~2ms live) is not exercised
            # by any test in this file; only the mid-tool-call case
            # (TRIGGER_HOLD_FOR_ABORT) is. A time-based fallback ack was
            # deliberately NOT added here: it would race the deterministic
            # 0.3s delay TRIGGER_HOLD_FOR_ABORT's own abort path uses to
            # widen the settle-gate test window, and could re-introduce the
            # exact wrong-order bug (ack before agent_settled) this fix
            # exists to eliminate. If a future test needs the no-tool-in-
            # flight abort path, it needs its own explicit trigger that
            # calls _send_abort_response_once() itself, not a timer race.
        else:
            write_msg({"type": "response", "command": verb, "success": False, "error": "Unknown command: %s" % verb})


if __name__ == "__main__":
    main()
