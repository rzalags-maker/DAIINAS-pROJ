"""Shared read-only account-topic limits; no provider transport or signing."""
import threading
import time

TOPICS = ("balance", "orders", "positions", "positions_settings")

class AccountStateError(RuntimeError):
    """Fixed local error category only."""


class AccountReadBudget:
    """Shared REST/WS account-topic budget from the pinned public contract.

    Optional to the existing observer, scoped to this worker. Waiting happens in
    REST threads or via to_thread for WS; never blocks the event-loop writer.
    """
    def __init__(self, *, clock=None):
        self.clock = clock or time.monotonic
        self.events = {topic: [] for topic in TOPICS}
        self.lock = threading.Lock()
        self.stopped = threading.Event()

    def acquire(self, topics):
        topics = tuple(topics)
        if not topics or len(set(topics)) != len(topics) or not set(topics) <= set(TOPICS):
            raise AccountStateError("INVALID_BUDGET_TOPIC")
        while not self.stopped.is_set():
            with self.lock:
                now = self.clock()
                delay = 0
                for topic in topics:
                    history = [t for t in self.events[topic] if now - t < 10]
                    self.events[topic] = history
                    one, ten = (1, 5) if topic == "positions_settings" else (5, 20)
                    recent = [t for t in history if now - t < 1]
                    if len(recent) >= one:
                        delay = max(delay, recent[-one] + 1 - now)
                    if len(history) >= ten:
                        delay = max(delay, history[-ten] + 10 - now)
                if delay <= 0:
                    for topic in topics:
                        self.events[topic].append(now)
                    return
            self.stopped.wait(delay + 0.001)
        raise AccountStateError("OBSERVATION_STOPPED")

    def stop(self):
        self.stopped.set()
