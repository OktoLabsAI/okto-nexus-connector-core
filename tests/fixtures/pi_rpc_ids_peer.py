"""Small ID-echo Pi RPC peer for concurrent and late-response tests."""

import json
import sys
import threading
import time


write_lock = threading.Lock()
pair = []


def respond(request):
    with write_lock:
        sys.stdout.write(json.dumps({
            "type": "response", "id": request["id"],
            "command": request["type"], "success": True,
            "data": {"tag": request.get("tag")},
        }) + "\n")
        sys.stdout.flush()


for line in sys.stdin:
    request = json.loads(line)
    if request.get("tag") == "late":
        threading.Thread(target=lambda value=request: (
            time.sleep(0.2), respond(value)), daemon=True).start()
    elif request.get("tag") in {"first", "second"}:
        pair.append(request)
        if len(pair) == 2:
            respond(pair[1])
            respond(pair[0])
            pair.clear()
    else:
        respond(request)
