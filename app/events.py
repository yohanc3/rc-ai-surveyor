"""Fan-out event bus backing the Server-Sent Events endpoint."""

from __future__ import annotations

import json
import queue
import threading

# Each subscriber gets its own bounded queue. A browser that stops reading must
# never be able to grow the backlog without limit, so the oldest event is
# dropped instead.
QUEUE_SIZE = 64


class EventBus:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue] = set()
        self._last: dict | None = None
        self._dropped = 0

    def publish(self, event: dict) -> None:
        payload = dict(event)
        with self._lock:
            self._last = payload
            subscribers = list(self._subscribers)
        for sub in subscribers:
            self._offer(sub, payload)

    def _offer(self, sub: queue.Queue, payload: dict) -> None:
        try:
            sub.put_nowait(payload)
        except queue.Full:
            try:
                sub.get_nowait()  # drop the oldest
            except queue.Empty:
                pass
            try:
                sub.put_nowait(payload)
            except queue.Full:
                pass
            with self._lock:
                self._dropped += 1

    def subscribe(self) -> queue.Queue:
        sub: queue.Queue = queue.Queue(maxsize=QUEUE_SIZE)
        with self._lock:
            self._subscribers.add(sub)
        return sub

    def unsubscribe(self, sub: queue.Queue) -> None:
        with self._lock:
            self._subscribers.discard(sub)

    @property
    def subscriber_count(self) -> int:
        with self._lock:
            return len(self._subscribers)

    @property
    def dropped(self) -> int:
        with self._lock:
            return self._dropped


def sse_frame(event: dict) -> bytes:
    """Encode one event in the text/event-stream format."""
    return f"data: {json.dumps(event)}\n\n".encode("utf-8")


def sse_comment(text: str = "keepalive") -> bytes:
    """A comment line keeps the connection open through idle proxies."""
    return f": {text}\n\n".encode("utf-8")
