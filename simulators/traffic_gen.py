"""Synthetic traffic generator.

Posts realistic login / transaction / SIM-change events to a running API at an
adjustable rate. Talk to the API over HTTP only — this module has no access to
the backend code.

Usage from the repo root:
    python -m simulators.traffic_gen --rate 2 --duration 60
"""

import argparse
import random
import sys
import time
from datetime import datetime, timezone

import requests

CITIES = ["Haveri", "Bengaluru", "Mysuru", "Hubballi", "Mangaluru", "Delhi"]
DEVICES = ["dev-android-a", "dev-iphone-b", "dev-laptop-c", "dev-tablet-d", "dev-kiosk-e"]
FLAGGED_DEVICES = ["dev-fraud-x1", "dev-fraud-x2"]
CHANNELS = ["mobile", "web", "atm", "branch"]


def _iso_now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def build_event(rng, customer_id):
    """Return (event_type, event_dict) with realistic-but-synthetic signals."""
    kind = rng.choices(["transaction", "login", "sim_change"], weights=[55, 30, 15])[0]

    if kind == "transaction":
        style = rng.choices(["normal", "large", "fraud"], weights=[70, 20, 10])[0]
        if style == "fraud":
            amount = rng.uniform(250_000, 2_500_000)
            city = rng.choice(["Delhi", "Mumbai", "Chennai"])
            device = rng.choice(FLAGGED_DEVICES)
        elif style == "large":
            amount = rng.uniform(120_000, 900_000)
            city = rng.choice(CITIES)
            device = rng.choice(DEVICES)
        else:
            amount = rng.uniform(500, 90_000)
            city = rng.choice(CITIES)
            device = rng.choice(DEVICES)
        event = {
            "amount": round(amount, 2),
            "txn_type": rng.choice(["transfer", "payment", "withdrawal", "upi"]),
            "channel": rng.choice(CHANNELS),
            "device_id": device,
            "ip_address": "203.0.113.%d" % rng.randint(1, 250),
            "city": city,
            "timestamp": _iso_now(),
        }
    elif kind == "login":
        event = {
            "success": rng.random() < 0.93,
            "channel": rng.choice(["mobile", "web"]),
            "device_id": rng.choice(DEVICES + FLAGGED_DEVICES),
            "ip_address": "198.51.100.%d" % rng.randint(1, 250),
            "city": rng.choice(CITIES),
            "timestamp": _iso_now(),
        }
        return "login", event

    else:  # sim_change
        event = {
            "sim_id": "SIM-%04d" % rng.randint(1000, 9999),
            "device_id": rng.choice(DEVICES + FLAGGED_DEVICES),
            "ip_address": "192.0.2.%d" % rng.randint(1, 250),
            "timestamp": _iso_now(),
        }
    return "transaction" if kind == "transaction" else "sim_change", event


def get_token(base_url, username, password):
    r = requests.post(f"{base_url}/api/auth/login",
                      json={"username": username, "password": password}, timeout=10)
    if r.status_code == 200:
        return r.json()["token"]
    r = requests.post(f"{base_url}/api/auth/register",
                      json={"username": username, "password": password, "role": "customer"},
                      timeout=10)
    if r.status_code in (200, 201):
        return r.json()["token"]
    raise SystemExit(f"Could not authenticate as {username}: {r.status_code} {r.text}")


def run(base_url, rate, duration, username, password, seed):
    rng = random.Random(seed)
    token = get_token(base_url, username, password)
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    print(f"traffic_gen connected to {base_url} as {username} @ {rate} ev/s for {duration}s")

    deadline = time.time() + duration
    sent = 0
    by_decision = {}
    while time.time() < deadline:
        customer_id = rng.randint(1, 5)
        event_type, event = build_event(rng, customer_id)
        try:
            resp = requests.post(
                f"{base_url}/api/risk/evaluate",
                json={"customer_id": customer_id, "event_type": event_type, "event": event},
                headers=headers, timeout=10)
        except requests.RequestException as exc:
            print(f"[error] {exc}")
            time.sleep(1 / max(rate, 0.1))
            continue
        sent += 1
        if resp.status_code == 200:
            body = resp.json()
            by_decision[body.get("decision", "?")] = by_decision.get(body.get("decision", "?"), 0) + 1
            print(f"#{sent} [{event_type}] -> {body.get('decision')} "
                  f"risk={body.get('risk_score')} reasons={len(body.get('reasons', []))}")
        else:
            print(f"#{sent} [{event_type}] HTTP {resp.status_code}: {resp.text[:200]}")
        time.sleep(1 / max(rate, 0.1))

    print(f"\nDone. Sent {sent} events. Decisions: {by_decision}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="SIM-swap fraud traffic generator")
    parser.add_argument("--url", default="http://localhost:5000")
    parser.add_argument("--rate", type=float, default=1.0, help="events per second")
    parser.add_argument("--duration", type=float, default=60, help="seconds to run")
    parser.add_argument("--username", default="sim-customer")
    parser.add_argument("--password", default="demo123")
    parser.add_argument("--seed", type=int, default=7)
    args = parser.parse_args(sys.argv[1:])
    run(args.url, args.rate, args.duration, args.username, args.password, args.seed)