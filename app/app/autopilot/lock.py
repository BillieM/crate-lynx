from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Self

from redis import Redis

logger = logging.getLogger(__name__)

_RENEW_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("pexpire", KEYS[1], ARGV[2])
end
return 0
"""
_RELEASE_SCRIPT = """
if redis.call("get", KEYS[1]) == ARGV[1] then
  return redis.call("del", KEYS[1])
end
return 0
"""


class LockUnavailableError(TimeoutError):
    pass


class LockOwnershipLostError(RuntimeError):
    pass


@dataclass(slots=True)
class RenewableRedisLock:
    """A token-owned lease with periodic renewal and atomic release."""

    connection: Any
    key: str
    ttl_seconds: float
    wait_seconds: float = 0
    retry_interval_seconds: float = 0.25
    renewal_interval_seconds: float | None = None
    token: str = field(default_factory=lambda: uuid.uuid4().hex)
    _acquired: bool = field(default=False, init=False, repr=False)
    _lost: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _stop: threading.Event = field(
        default_factory=threading.Event, init=False, repr=False
    )
    _renewal_thread: threading.Thread | None = field(
        default=None, init=False, repr=False
    )

    @classmethod
    def from_url(
        cls,
        redis_url: str,
        *,
        key: str,
        ttl_seconds: float,
        wait_seconds: float = 0,
        retry_interval_seconds: float = 0.25,
        renewal_interval_seconds: float | None = None,
    ) -> RenewableRedisLock:
        return cls(
            connection=Redis.from_url(redis_url),
            key=key,
            ttl_seconds=ttl_seconds,
            wait_seconds=wait_seconds,
            retry_interval_seconds=retry_interval_seconds,
            renewal_interval_seconds=renewal_interval_seconds,
        )

    def __enter__(self) -> Self:
        self.acquire()
        return self

    def __exit__(self, exc_type, exc, traceback) -> None:
        self.release()

    def acquire(self) -> None:
        if self._acquired:
            return
        if self.ttl_seconds <= 0:
            raise ValueError("Lock TTL must be positive")
        deadline = time.monotonic() + max(0, self.wait_seconds)
        ttl_ms = max(1, int(self.ttl_seconds * 1000))
        while True:
            if self.connection.set(self.key, self.token, nx=True, px=ttl_ms):
                self._acquired = True
                self._lost.clear()
                self._stop.clear()
                self._start_renewal()
                return
            if time.monotonic() >= deadline:
                raise LockUnavailableError(
                    f"Timed out waiting for distributed lock {self.key}"
                )
            time.sleep(self.retry_interval_seconds)

    def assert_owned(self) -> None:
        if not self._acquired or self._lost.is_set():
            raise LockOwnershipLostError(
                f"Distributed lock ownership was lost for {self.key}"
            )

    def renew(self) -> None:
        self.assert_owned()
        renewed = self.connection.eval(
            _RENEW_SCRIPT,
            1,
            self.key,
            self.token,
            max(1, int(self.ttl_seconds * 1000)),
        )
        if not renewed:
            self._lost.set()
            raise LockOwnershipLostError(
                f"Distributed lock ownership was lost for {self.key}"
            )

    def release(self) -> None:
        if not self._acquired:
            return
        self._stop.set()
        if self._renewal_thread is not None:
            self._renewal_thread.join(timeout=max(1.0, self._renewal_interval() * 2))
        try:
            self.connection.eval(
                _RELEASE_SCRIPT,
                1,
                self.key,
                self.token,
            )
        finally:
            self._acquired = False
            self._renewal_thread = None

    def _start_renewal(self) -> None:
        self._renewal_thread = threading.Thread(
            target=self._renew_until_stopped,
            name=f"redis-lock-renewal:{self.key}",
            daemon=True,
        )
        self._renewal_thread.start()

    def _renew_until_stopped(self) -> None:
        interval = self._renewal_interval()
        while not self._stop.wait(interval):
            try:
                self.renew()
            except Exception:
                self._lost.set()
                logger.exception("Failed to renew distributed lock key=%s", self.key)
                return

    def _renewal_interval(self) -> float:
        configured = self.renewal_interval_seconds
        if configured is not None:
            if configured <= 0 or configured >= self.ttl_seconds:
                raise ValueError(
                    "Renewal interval must be positive and below the lock TTL"
                )
            return configured
        return max(0.05, self.ttl_seconds / 3)
