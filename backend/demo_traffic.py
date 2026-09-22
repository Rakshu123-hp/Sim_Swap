"""Autonomous demo-event generator for the deployed application.

Generates realistic synthetic transactions / logins / SIM changes for *existing*
customers in the database, scores them through the exact same code path as
/api/risk/evaluate (backend.api.service.evaluate_and_store), and persists the
results — no local laptop required.

Controlled by environment variables (safe defaults keep production quiet):

    ENABLE_DEMO_TRAFFIC   false | true   (must be explicitly enabled)
    DEMO_TRAFFIC_INTERVAL 5              seconds between batches
    DEMO_TRAFFIC_RATE     1              events per batch

Gunicorn workers: only ONE generator runs at a time, even with multiple
workers. Every cycle the manager must either claim (INSERT) or extend (renew)
a unique agents row with a time lease; a stale lease lets another worker take
over, so a crashed owner is replaced without duplicating generation. The thread
is a daemon with an explicit stop, so it never blocks shutdown.
"""

import logging
import os
import random
import threading

from backend.api import service
from backend.db import models
from simulators.traffic_gen import build_event

log = logging.getLogger("demo_traffic")


def env_flag(name, default=False):
    value = (os.getenv(name) or "").strip().lower()
    if not value:
        return default
    return value in {"1", "true", "yes", "on"}


def env_int(name, default):
    try:
        return int(os.getenv(name, "").strip() or default)
    except (TypeError, ValueError):
        return default


class DemoTrafficManager:
    """Runs a single, guarded, optional background generator."""

    def __init__(self, enabled=False, interval=5, rate=1):
        self.enabled = bool(enabled)
        self.interval = max(1, int(interval))
        self.rate = max(1, int(rate))
        self._stop = threading.Event()
        self._thread = None
        self._owned = False
        self._agent_key = "demo-traffic"

    # ------------------------------------------------------------ lifecycle

    @classmethod
    def from_env(cls):
        return cls(
            enabled=env_flag("ENABLE_DEMO_TRAFFIC"),
            interval=env_int("DEMO_TRAFFIC_INTERVAL", 5),
            rate=env_int("DEMO_TRAFFIC_RATE", 1),
        )

    def start(self):
        if not self.enabled or self._thread is not None:
            return
        self._thread = threading.Thread(
            target=self._loop, name="demo-traffic", daemon=True)
        self._thread.start()
        log.info("demo traffic started (interval=%ss rate=%s/batch)",
                 self.interval, self.rate)

    def stop(self):
        self._stop.set()

    def loop_join(self, timeout=None):
        if self._thread is not None:
            self._thread.join(timeout)

    # ------------------------------------------------------------ worker guard

    def _claim_renew(self):
        if self._owned:
            if models.demo_traffic_renew(self._agent_key):
                return True
            self._owned = False
        if models.demo_traffic_claim(self._agent_key):
            self._owned = True
            return True
        return False

    # ------------------------------------------------------------ generator

    def generate_batch(self):
        """Generate one batch of events against existing customers."""
        customers = models.list_customers()
        if not customers:
            return 0
        rng = random.Random()
        count = 0
        for _ in range(self.rate):
            customer = rng.choice(customers)
            event_type, event = build_event(rng, customer["id"])
            try:
                service.evaluate_and_store(customer, event_type, event,
                                           viewer="demo-traffic")
                count += 1
            except Exception as exc:  # never take the generator down with an event
                log.warning("demo event failed for customer %s: %s",
                            customer.get("id"), exc)
        models.upsert_heartbeat(self._agent_key)
        return count

    def _loop(self):
        log.info("demo traffic loop running")
        while not self._stop.is_set():
            try:
                if self._claim_renew():
                    self.generate_batch()
            except Exception as exc:  # keep the loop alive on unexpected errors
                log.warning("demo traffic cycle error: %s", exc)
            self._stop.wait(self.interval)