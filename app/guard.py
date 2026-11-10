"""Cost and abuse guard for live (LLM-backed) runs.

All state is held in memory. On Azure Container Apps with scale-to-zero, the counters
reset when the container restarts after an idle period. docs/COSTS.md explains why
this is acceptable and which platform-level limits back it up.
"""
from __future__ import annotations

import hmac
import threading
import time
from dataclasses import dataclass
from typing import Callable

from app.config import Settings


@dataclass
class Decision:
    allowed: bool
    status: int = 200
    reason: str = ""


class UsageGuard:
    def __init__(self, settings: Settings, clock: Callable[[], float] = time.time) -> None:
        self.s = settings
        self._clock = clock
        self._lock = threading.Lock()
        self._day = ""
        self._runs = 0
        self._spent = 0.0
        self._per_ip: dict[str, int] = {}
        self._in_progress = 0
        self._last_start = 0.0

    def _roll_day(self) -> None:
        day = time.strftime("%Y-%m-%d", time.gmtime(self._clock()))
        if day != self._day:
            self._day, self._runs, self._spent, self._per_ip = day, 0, 0.0, {}

    def status(self) -> dict:
        with self._lock:
            self._roll_day()
            return {
                "runs_today": self._runs,
                "runs_left_today": max(self.s.daily_max_runs - self._runs, 0),
                "budget_left_usd": round(max(self.s.daily_budget_usd - self._spent, 0.0), 4),
                "busy": self._in_progress > 0,
            }

    def acquire(self, ip: str, code: str | None) -> Decision:
        s = self.s
        if s.provider == "none":
            return Decision(False, 503, "Live agents are not configured on this deployment. Use the recorded replay.")
        if not s.live_enabled:
            return Decision(False, 503, "Live agent runs are currently switched off by the owner. Use the recorded replay.")
        if s.access_code and not hmac.compare_digest(str(code or ""), s.access_code):
            return Decision(False, 403, "An access code is required for live runs.")
        with self._lock:
            self._roll_day()
            now = self._clock()
            if self._in_progress > 0:
                return Decision(False, 429, "Another live run is in progress. Try again in a minute.")
            wait = self.s.cooldown_s - (now - self._last_start)
            if wait > 0:
                return Decision(False, 429, f"Please wait {int(wait) + 1}s before starting another live run.")
            if self._runs >= s.daily_max_runs:
                return Decision(False, 429, "The daily limit of live runs was reached. Use the recorded replay.")
            if self._per_ip.get(ip, 0) >= s.per_ip_max_runs:
                return Decision(False, 429, "The per-visitor limit of live runs for today was reached.")
            if self._spent >= s.daily_budget_usd:
                return Decision(False, 429, "The daily model budget was reached. Use the recorded replay.")
            self._in_progress += 1
            self._runs += 1
            self._per_ip[ip] = self._per_ip.get(ip, 0) + 1
            self._last_start = now
            return Decision(True)

    def release(self, cost_usd: float) -> None:
        with self._lock:
            self._in_progress = max(self._in_progress - 1, 0)
            self._spent += max(cost_usd, 0.0)
