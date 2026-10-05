
import json
import os
import sys
import threading
import time

LOG_PATH = sys.argv[1] if len(sys.argv) > 1 else None
_write_lock = threading.Lock()
_log_lock = threading.Lock()
_counter_lock = threading.Lock()
_thread_counter = 0
_turn_counter = 0
_approval_lock = threading.Lock()
_approval_waiters = {}


def write_msg(obj):
    with _write_lock:
        sys.stdout.write(json.dumps(obj) + "\n")
        sys.stdout.flush()


def log(entry):
    if not LOG_PATH:
        return
    with _log_lock:
        with open(LOG_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(entry) + "\n")


def next_thread_id():
    global _thread_counter
    with _counter_lock:
        _thread_counter += 1
        return "th_%d" % _thread_counter


def next_turn_id():
    global _turn_counter
    with _counter_lock:
        _turn_counter += 1
        return "turn_%d" % _turn_counter


def handle_turn(thread_id, turn_id, text, req_id):
    if "TRIGGER_ERROR" in text:
        write_msg({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32000, "message": "boom"}})
        return

    write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"turn": {"id": turn_id, "status": "inProgress"}}})
    write_msg({"method": "turn/started", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "inProgress"}}})

    if any(trigger in text for trigger in ("TRIGGER_APPROVAL_HOLD", "TRIGGER_INPUT_HOLD", "TRIGGER_MCP_PERMISSION_HOLD")):
        approval_id = 10000 + int(turn_id.split("_")[-1])
        waiter = threading.Event()
        with _approval_lock:
            _approval_waiters[approval_id] = waiter
        asking_input = "TRIGGER_INPUT_HOLD" in text
        method = ("item/tool/requestUserInput" if asking_input else
                  "item/commandExecution/requestApproval")
        params = {"threadId": thread_id, "turnId": turn_id,
                  "itemId": "item_" + turn_id}
        if "TRIGGER_MCP_PERMISSION_HOLD" in text:
            method = "mcpServer/elicitation/request"
            params = {"threadId": thread_id, "turnId": turn_id,
                "serverName": "nexus_test", "mode": "form",
                "_meta": {"codex_approval_kind": "mcp_tool_call", "persist": ["session", "always"],
                          "tool_params": {"agent_id": "agent", "handoff_id": "work"}},
                "message": 'Allow the nexus_test MCP server to run tool "handoff_get"?',
                "requestedSchema": {"type": "object", "properties": {}}}
        elif asking_input:
            params.update({"isBlocking": True,
                           "questions": [{"id": "answer", "header": "Choice",
                                          "question": "Proceed?",
                                          "isOther": True,
                                          "options": [{"label": "yes",
                                                       "description": "Proceed"}]}]})
        else:
            params["availableDecisions"] = ["accept", "decline"]
        write_msg({"jsonrpc": "2.0", "id": approval_id,
                   "method": method, "params": params})
        if not waiter.wait(10):
            log({"approval_timeout": approval_id})
            return
        write_msg({"method": "turn/completed", "params": {"threadId": thread_id,
                   "turn": {"id": turn_id, "status": "completed"}}})
        return

    if "TRIGGER_SERVER_REQUEST" in text:
        # Live-verified real ServerRequest method name (codex app-server
        # generate-json-schema + a live probe against 0.144.6/LAN box,
        # 2026-09-20): "item/tool/call" is not a real ServerRequest method -
        # the real ones are item/commandExecution/requestApproval,
        # item/fileChange/requestApproval, item/tool/requestUserInput, etc.
        # Harmless either way (this connector's reply_method_not_found does
        # not branch on the method name - any id+method combo gets -32601),
        # but corrected for fidelity to the real wire shape.
        write_msg({"jsonrpc": "2.0", "id": 9001, "method": "item/commandExecution/requestApproval", "params": {}})

    if "TRIGGER_MALFORMED" in text:
        with _write_lock:
            sys.stdout.write("not-json-garbage\n")
            sys.stdout.flush()

    if "TRIGGER_HOSTILE_JSON" in text:
        with _write_lock:
            sys.stdout.write('{"method":"item/started","method":"item/completed"}\n')
            sys.stdout.write('{"method":"item/started","params":{"value":NaN}}\n')
            sys.stdout.write('{"method":"item/started","value":"\\ud800"}\n')
            sys.stdout.write('{"method":"item/started","value":9007199254740992}\n')
            sys.stdout.write("[]\n")
            sys.stdout.write("[" * 20000 + "0" + "]" * 20000 + "\n")
            sys.stdout.flush()

    if "TRIGGER_EMPTY_METHOD" in text:
        # JSON-RPC-legal (parses fine) but domain-invalid: HarnessEvent
        # rejects an empty native_event. Reproduces the reader-thread wedge
        # class distinct from TRIGGER_MALFORMED's JSONDecodeError.
        write_msg({"method": "", "params": {}})

    if "TRIGGER_ARRAY_PARAMS" in text:
        # JSON-RPC 2.0 explicitly permits "params" as an array. This
        # connector's _extract_thread_id calls params.get(...), which
        # raises AttributeError on a list - the second reader-thread-wedge
        # trigger shape.
        write_msg({"method": "item/started", "params": ["not", "a", "dict"]})

    if "TRIGGER_CRASH" in text:
        time.sleep(0.05)
        os._exit(7)

    if ("TRIGGER_FLOOD" in text or "TRIGGER_HISTORY_FLOOD" in text or
            "TRIGGER_BYTE_FLOOD" in text):
        flood_count = (13 if "TRIGGER_BYTE_FLOOD" in text else
                       2200 if "TRIGGER_HISTORY_FLOOD" in text else 140)
        delta = "x" * 80000 if "TRIGGER_BYTE_FLOOD" in text else None
        item_id = "item_" + turn_id
        write_msg({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id,
                   "item": {"id": item_id, "type": "agentMessage"}}})
        for index in range(flood_count):
            write_msg({"method": "item/agentMessage/delta", "params": {
                "threadId": thread_id, "turnId": turn_id, "itemId": item_id,
                "delta": delta if delta is not None else "flood-%d" % index}})
        write_msg({"method": "turn/completed", "params": {"threadId": thread_id,
                   "turn": {"id": turn_id, "status": "completed"}}})
        return

    if "TRIGGER_HOLD" in text:
        return

    if "TRIGGER_DELAYED_COMPLETE" in text:
        # A deliberate pause between turn/started and the rest of the turn's
        # events, wide enough for a test to reliably call end() WHILE the
        # turn is still in flight (i.e. before turn/completed is even
        # written) rather than racing a turn that completes near-instantly.
        time.sleep(0.3)

    item_id = "item_" + turn_id
    write_msg({"method": "item/started", "params": {"threadId": thread_id, "turnId": turn_id, "item": {"id": item_id, "type": "agentMessage"}, "startedAtMs": 0}})
    write_msg({"method": "item/agentMessage/delta", "params": {"threadId": thread_id, "turnId": turn_id, "itemId": item_id, "delta": text}})
    write_msg({"method": "item/completed", "params": {"threadId": thread_id, "turnId": turn_id, "item": {"id": item_id, "type": "agentMessage", "text": text}, "completedAtMs": 0}})
    write_msg({"method": "turn/completed", "params": {"threadId": thread_id, "turn": {"id": turn_id, "status": "completed"}}})


def main():
    for raw in sys.stdin:
        line = raw.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        method = msg.get("method")
        req_id = msg.get("id")
        params = msg.get("params") or {}

        if method is None:
            # A response to a request WE (the fake server) sent - e.g. the
            # connector's -32601 reply to our unsolicited server-request.
            log({"response_to_server_request": msg})
            with _approval_lock:
                waiter = _approval_waiters.pop(req_id, None)
            if waiter is not None:
                waiter.set()
            continue

        if method == "initialize":
            write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"userAgent": "okto-nexus/0.156.1"}})
        elif method == "thread/start":
            thread_id = next_thread_id()
            if params.get("_early_notify"):
                write_msg({"method": "thread/started", "params": {"thread": {"id": thread_id}}})
            write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"thread": {"id": thread_id}}})
        elif method == "turn/start":
            log({"method": "turn/start", "params": params})
            thread_id = params["threadId"]
            text = params["input"][0]["text"]
            turn_id = next_turn_id()
            threading.Thread(target=handle_turn, args=(thread_id, turn_id, text, req_id), daemon=True).start()
        elif method == "turn/steer":
            log({"method": "turn/steer", "params": params})
            write_msg({"jsonrpc": "2.0", "id": req_id, "result": {}})
        elif method == "turn/interrupt":
            log({"method": "turn/interrupt", "params": params})
            # RES-C2 fix: real capture (EV-CX-001-raw_capture_interrupt.jsonl,
            # live-verified against codex 0.144.6/.152) shows the RPC result
            # and turn/completed(status="interrupted") arrive TOGETHER, no
            # separate settle notification and no delay - the fake used to
            # ack and then emit NOTHING further, an omission that let no test
            # observe correct-or-wrong post-interrupt ordering at all. Now
            # matches the real wire: result first, then turn/completed with
            # status "interrupted" for the SAME turnId, written back-to-back.
            write_msg({"jsonrpc": "2.0", "id": req_id, "result": {}})
            write_msg(
                {
                    "method": "turn/completed",
                    "params": {
                        "threadId": params["threadId"],
                        "turn": {"id": params["turnId"], "status": "interrupted"},
                    },
                }
            )
        elif method == "thread/unsubscribe":
            log({"method": "thread/unsubscribe", "params": params})
            # Live-verified result shape (same probe as above): the real
            # response is {"status": "unsubscribed"}, not {"status": "ok"}.
            # Harmless either way - this connector discards a successful
            # fire-and-forget response entirely and never reads this field -
            # but corrected for fidelity.
            write_msg({"jsonrpc": "2.0", "id": req_id, "result": {"status": "unsubscribed"}})
        else:
            write_msg({"jsonrpc": "2.0", "id": req_id, "error": {"code": -32601, "message": "unhandled by fake server"}})


if __name__ == "__main__":
    main()
