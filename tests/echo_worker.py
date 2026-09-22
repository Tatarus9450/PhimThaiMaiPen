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
    print(json.dumps({"id": request["id"], "ok": not request.get("error"),
                      "error": request.get("error", ""), "text": request.get("text", ""), "pid": os.getpid(),
                      "environment": {key: os.environ.get(key) for key in request.get("environment_keys", [])}}), flush=True)
