"""Offline-only candidate: reuse the original admission/budget/stop machinery.

Not imported by a production driver. Maximum remains the validated twenty;
24/32-way production requires a separate bounded benchmark and safe switch.
"""
from collections import deque

from run_voc_concurrency_v995 import base


class RecoveryPolicyCandidate(base.Governor):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.operating_cap = self.maximum
        self.health_window = deque()
        self.fast_streak = 0
        self.last_adjustment = float('-inf')

    def cap(self, value):
        if type(value) is not int or not 1 <= value <= self.maximum:
            raise ValueError('Invalid operating cap')
        with self.cv:
            self.operating_cap = value
            self.target = min(self.target, value)
            self.cv.notify_all()

    def finish(self, attempt_id, usage=None, status=None, seconds=0, network_error=False):
        with self.cv:
            prior, reduction, cooldown = self.target, self.last_reduction, self.cooldown_until
            # Reuse actual reservation release, measured/unknown usage handling,
            # rolling token accounting, and lock notification. Replace only
            # the operating-target decision, never budgets or source acceptance.
            super().finish(attempt_id, usage, status, seconds, network_error)
            now = self.clock()
            successful = status is not None and 200 <= status < 300
            transient = network_error or status in {408, 409} or (successful and seconds >= 60)
            self.health_window.append((now, transient))
            while self.health_window and self.health_window[0][0] < now - 60:
                self.health_window.popleft()
            failures = sum(bad for _, bad in self.health_window)
            clustered = failures >= 3 or (len(self.health_window) >= 10
                                         and failures / len(self.health_window) >= .10)
            self.target, self.last_reduction = prior, reduction
            self.cooldown_until = cooldown
            if status == 429 or (status or 0) >= 500:
                self.target = max(1, prior // 2)
                self.last_reduction = self.last_adjustment = now
                self.fast_streak = 0
                self.cooldown_until = max(cooldown, now + (60 if status == 429 else 5))
            elif transient:
                self.fast_streak = 0
                if network_error or status in {408, 409}:
                    self.cooldown_until = max(cooldown, now + 5)
                if clustered and now - self.last_adjustment >= 15:
                    # Transient/latency evidence alone does not serialise a
                    # twenty-way job. Sustained 429/5xx can still reach one.
                    self.target = min(prior, max(min(4, self.operating_cap), prior // 2))
                    if self.target < prior:
                        self.last_reduction = self.last_adjustment = now
            elif successful and seconds < 30:
                self.fast_streak += 1
                if (self.fast_streak >= 10 and now >= self.cooldown_until
                        and now - self.last_reduction >= 30
                        and now - self.last_adjustment >= 10):
                    self.target = min(self.operating_cap, prior + 2)
                    self.fast_streak = 0
                    self.last_adjustment = now
            self.target = min(self.target, self.operating_cap, self.maximum)
            self.cv.notify_all()
