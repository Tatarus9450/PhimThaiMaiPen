"""Protocol fixture: exercises real child-process lifecycle without an ASR download."""
import json
import os
import sys
import time

print(json.dumps({"event": "ready"}), flush=True)
for line in sys.stdin:
    request = json.loads(line)
    if request.get("crash"):
        os._exit(23)
    time.sleep(request.get("delay", 0))
    print(json.dumps({"id": request["id"], "ok": True, "text": request.get("text", ""), "pid": os.getpid()}), flush=True)
