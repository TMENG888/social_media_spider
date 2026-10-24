"""Process-local HTTP admission control; never changes prompts or cache keys."""
import hashlib
import json
import threading
import time
import uuid
from collections import deque
from pathlib import Path


class SoftStop(RuntimeError):
    """Not an OSError: the original API runner must not retry a soft stop."""


class RequestBudgetError(RuntimeError):
    pass


def request_budget(body):
    if body.get("enable_thinking") is not False:
        raise RequestBudgetError("Only the existing non-thinking requests are allowed")
    output = body.get("max_tokens")
    if type(output) is not int or not 1 <= output <= 131072:
        raise RequestBudgetError("Output reservation outside the supplied model limit")
    # UTF-8 bytes conservatively approximate byte-tokenization, plus template
    # overhead. Not a claim of provider-exact tokenization/account quota.
    encoded = json.dumps(body, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    input_estimate = len(encoded) + 4096
    if input_estimate > 991000 or input_estimate + output > 1048576:
        raise RequestBudgetError("Conservative input/context estimate exceeds supplied limit")
    return input_estimate, output, hashlib.sha256(encoded).hexdigest()


def measured_tokens(usage):
    if not isinstance(usage, dict):
        return None
    p, c = usage.get("prompt_tokens"), usage.get("completion_tokens")
    if type(p) is int and p >= 0 and type(c) is int and c >= 0:
        return p + c
    return None


class Governor:
    def __init__(self, maximum=20, tpm=3500000, rpm=300, stop=None,
                 clock=time.monotonic):
        if not 1 <= maximum <= 20:
            raise ValueError("This authorized launcher permits at most 20 HTTP attempts")
        self.maximum = maximum
        self.target = maximum
        self.tpm, self.rpm = tpm, rpm
        self.stop = stop or (lambda: False)
        self.clock = clock
        self.cv = threading.Condition()
        self.starts, self.finished = deque(), deque()
        self.active = {}
        self.cooldown_until = 0
        self.last_reduction = 0
        self.healthy = 0
        self.total_attempts = 0
        self.peak_active = 0

    def _prune(self, now):
        while self.starts and self.starts[0] <= now - 60:
            self.starts.popleft()
        while self.finished and self.finished[0][0] <= now - 60:
            self.finished.popleft()
        # Active reservations never expire while the request is in flight.

    def _reserved(self):
        return sum(self.active.values()) + sum(x[1] for x in self.finished)

    def acquire(self, reservation):
        if reservation > self.tpm:
            raise RequestBudgetError("One request exceeds the local TPM budget")
        with self.cv:
            while True:
                if self.stop():
                    raise SoftStop("Soft stop: no new HTTP attempt sent")
                now = self.clock()
                self._prune(now)
                if (now >= self.cooldown_until and len(self.active) < self.target
                        and len(self.starts) < self.rpm
                        and self._reserved() + reservation <= self.tpm):
                    attempt_id = uuid.uuid4().hex
                    self.active[attempt_id] = reservation
                    self.starts.append(now)
                    self.total_attempts += 1
                    self.peak_active = max(self.peak_active, len(self.active))
                    return attempt_id
                self.cv.wait(timeout=0.25)

    def finish(self, attempt_id, usage=None, status=None, seconds=0, network_error=False):
        with self.cv:
            now = self.clock()
            reserve = self.active.pop(attempt_id)
            measured = measured_tokens(usage)
            self.finished.append((now, reserve if measured is None else measured))
            unhealthy = network_error or status in {408, 409, 429} or (status or 0) >= 500
            if unhealthy or seconds >= 60:
                self.target = max(min(10, self.maximum), self.target - 5)
                self.last_reduction, self.healthy = now, 0
                self.cooldown_until = max(self.cooldown_until, now + (60 if status == 429 else 5))
            elif status is not None and 200 <= status < 300 and seconds < 30:
                self.healthy += 1
                if self.healthy >= 20 and now - self.last_reduction >= 60:
                    self.target = min(self.maximum, self.target + 1)
                    self.healthy = 0
            self._prune(now)
            self.cv.notify_all()

    def snapshot(self):
        with self.cv:
            now = self.clock()
            self._prune(now)
            return {"max_concurrency": self.maximum, "effective_concurrency": self.target,
                    "active_http_attempts": len(self.active), "peak_active_http_attempts": self.peak_active,
                    "local_reserved_tokens": self._reserved(), "rolling_request_starts": len(self.starts),
                    "rolling_tpm_budget": self.tpm, "rolling_rpm_budget": self.rpm,
                    "cooldown_seconds": max(0, round(self.cooldown_until - now, 2)),
                    "http_attempts_since_start": self.total_attempts}


class ControlledPost:
    """Wrap each real HTTP attempt, including retries; cache hits bypass it."""
    def __init__(self, post, governor, directory, save_json):
        self.post, self.governor = post, governor
        self.directory, self.save_json = Path(directory), save_json
        self.state_lock = threading.Lock()

    def _state(self):
        with self.state_lock:
            self.save_json(self.directory / "concurrency_status.json",
                           {**self.governor.snapshot(), "updated_at": time.time(),
                            "ledger_role": "diagnostic only; do not add to calls ledger costs"})

    def __call__(self, url, body, key, timeout=120):
        input_estimate, output, body_hash = request_budget(body)
        reservation = input_estimate + output
        attempt_id = self.governor.acquire(reservation)
        path = self.directory / "http_attempts" / (attempt_id + ".json")
        record = {"attempt_id": attempt_id, "body_sha256": body_hash,
                  "started_at": time.time(), "model": body.get("model"),
                  "input_token_estimate": input_estimate, "output_token_reservation": output,
                  "state": "admitted_not_confirmed_sent", "usage": None,
                  "ledger_role": "diagnostic only; usage may duplicate calls ledger"}
        try:
            # Persist before sending. A write failure prevents this attempt.
            self.save_json(path, record)
            self._state()
        except BaseException:
            self.governor.finish(attempt_id)
            raise RuntimeError("Pre-send diagnostic write failed; no HTTP attempt sent")
        started = time.monotonic()
        usage, status, error = None, None, None
        try:
            response = self.post(url, body, key, timeout=timeout)
            status = response.status_code
            try:
                raw = response.json()
                usage = raw.get("usage") if isinstance(raw, dict) else None
            except (ValueError, KeyError, TypeError, UnicodeError):
                raw = None
            record.update(state="http_response_received", http_status=status, usage=usage)
            return response
        except BaseException as exc:
            error = type(exc).__name__
            record.update(state="transport_error_usage_unknown", error_type=error)
            raise
        finally:
            seconds = time.monotonic() - started
            self.governor.finish(attempt_id, usage, status, seconds, error is not None)
            record.update(finished_at=time.time(), seconds=round(seconds, 3),
                          usage_known=measured_tokens(usage) is not None)
            try:
                self.save_json(path, record)
                self._state()
            except BaseException:
                # Original runner can still save the actual response/usage.
                # The initial admitted record remains explicit unknown evidence.
                print(json.dumps({"attempt_diagnostic_write_failed": attempt_id,
                                  "usage_may_only_be_in_calls_ledger": True}), flush=True)
