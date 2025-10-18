#!/usr/bin/env python3
import json, os, signal, sys
from pathlib import Path

root = Path(__file__).resolve().parent
pidfile = root / "_pids.json"

if not pidfile.exists():
    print("No _pids.json found.")
    sys.exit(0)

pids = json.loads(pidfile.read_text())
for name in ["queue_releaser.py", "controller.py", "external_scaler.py"]:
    pid = pids.get(name)
    if pid:
        try:
            os.kill(pid, signal.SIGTERM)
            print(f"Sent SIGTERM to {name} (pid {pid})")
        except ProcessLookupError:
            print(f"{name} (pid {pid}) not running.")
print("Done.")
