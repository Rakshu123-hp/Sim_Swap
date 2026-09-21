"""Demo/monitoring agent heartbeat.

Pings POST /api/agents/heartbeat every N seconds so the dashboard can show the
agent as online (or stale if it stops beating).

Usage from the repo root:
    python -m simulators.heartbeat_agent --interval 10
"""

import argparse
import sys
import time
from datetime import datetime, timezone

import requests


def run(base_url, interval, name):
    print(f"heartbeat_agent '{name}' pinging {base_url} every {interval}s  (Ctrl-C to stop)")
    while True:
        try:
            resp = requests.post(f"{base_url}/api/agents/heartbeat",
                                 json={"agent_name": name}, timeout=10)
            ok = resp.status_code == 200
            now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            print(f"[{now}] agent={name} heartbeat -> HTTP {resp.status_code} {'ok' if ok else 'FAIL'}")
        except requests.RequestException as exc:
            print(f"[{datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')}] heartbeat error: {exc}")
        time.sleep(interval)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Synthetic agent heartbeat")
    parser.add_argument("--url", default="http://localhost:5000")
    parser.add_argument("--interval", type=int, default=10, help="seconds between beats")
    parser.add_argument("--name", default="traffic-agent-1")
    args = parser.parse_args(sys.argv[1:])
    run(args.url, args.interval, args.name)