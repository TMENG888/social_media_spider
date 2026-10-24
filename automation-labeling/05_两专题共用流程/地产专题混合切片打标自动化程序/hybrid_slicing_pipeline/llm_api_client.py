#!/usr/bin/env python3
"""Minimal OpenAI-compatible client with usage/cost accounting."""

from __future__ import annotations

import json
import os
import random
import time
from dataclasses import asdict, dataclass
from typing import Any

import requests


@dataclass
class CallMetrics:
    status: str
    http_status: int | None
    latency_seconds: float
    retries: int
    prompt_tokens: int | None
    cached_input_tokens: int | None
    completion_tokens: int | None
    total_tokens: int | None
    api_cost: float | None
    request_id: str
    error: str


class LlmApiClient:
    def __init__(
        self,
        base_url: str,
        model: str = "qwen3.7-flash",
        api_key: str | None = None,
        timeout: int = 120,
        max_retries: int = 2,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.api_key = api_key or os.environ.get("YS_LLM_API_KEY", "")
        if not self.api_key:
            raise ValueError("Missing YS_LLM_API_KEY environment variable")
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        })

    @staticmethod
    def _json_object(text: str) -> dict[str, Any]:
        value = text.strip()
        if value.startswith("```"):
            value = value.split("\n", 1)[-1]
            if value.endswith("```"):
                value = value[:-3]
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("Model response does not contain a JSON object")
        return json.loads(value[start : end + 1])

    @staticmethod
    def _cost(payload: dict[str, Any]) -> float | None:
        usage = payload.get("usage") or {}
        candidates = [payload.get("cost"), usage.get("cost"), usage.get("total_cost")]
        for item in candidates:
            try:
                if item is not None:
                    return float(item)
            except (TypeError, ValueError):
                pass
        return None

    @staticmethod
    def _cached_tokens(usage: dict[str, Any]) -> int:
        details = usage.get("prompt_tokens_details") or {}
        try:
            return max(0, int(details.get("cached_tokens") or 0))
        except (TypeError, ValueError):
            return 0

    def chat_json(self, system_prompt: str, user_prompt: str) -> tuple[dict[str, Any] | None, dict[str, Any]]:
        body = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0.1,
            "enable_thinking": False,
            "max_tokens": 2200,
        }
        started = time.perf_counter()
        last_error = ""
        http_status: int | None = None
        request_id = ""
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.post(
                    self.base_url + "/v1/chat/completions", json=body, timeout=self.timeout
                )
                http_status = response.status_code
                request_id = response.headers.get("x-request-id", "")
                if response.status_code == 401:
                    raise PermissionError("API authentication failed (401 Invalid token)")
                if response.status_code in {408, 409, 429, 500, 502, 503, 504}:
                    raise RuntimeError(f"Retryable HTTP {response.status_code}")
                response.raise_for_status()
                payload = response.json()
                if not request_id:
                    request_id = str(payload.get("id", ""))
                content = payload["choices"][0]["message"]["content"]
                usage = payload.get("usage") or {}
                try:
                    result = self._json_object(content)
                except Exception as exc:
                    # The gateway has already billed/used tokens. Preserve its
                    # usage rather than retrying a truncated/malformed answer.
                    metrics = CallMetrics(
                        status="failed_json",
                        http_status=response.status_code,
                        latency_seconds=round(time.perf_counter() - started, 3),
                        retries=attempt,
                        prompt_tokens=usage.get("prompt_tokens"),
                        cached_input_tokens=self._cached_tokens(usage),
                        completion_tokens=usage.get("completion_tokens"),
                        total_tokens=usage.get("total_tokens"),
                        api_cost=self._cost(payload),
                        request_id=request_id,
                        error=f"{type(exc).__name__}: {exc}"[:500],
                    )
                    return None, asdict(metrics)
                metrics = CallMetrics(
                    status="success",
                    http_status=response.status_code,
                    latency_seconds=round(time.perf_counter() - started, 3),
                    retries=attempt,
                    prompt_tokens=usage.get("prompt_tokens"),
                    cached_input_tokens=self._cached_tokens(usage),
                    completion_tokens=usage.get("completion_tokens"),
                    total_tokens=usage.get("total_tokens"),
                    api_cost=self._cost(payload),
                    request_id=request_id,
                    error="",
                )
                return result, asdict(metrics)
            except PermissionError as exc:
                last_error = str(exc)
                break
            except Exception as exc:  # network, server, JSON/schema errors
                last_error = f"{type(exc).__name__}: {exc}"
                if attempt < self.max_retries:
                    time.sleep((2 ** attempt) + random.random())
        metrics = CallMetrics(
            status="failed",
            http_status=http_status,
            latency_seconds=round(time.perf_counter() - started, 3),
            retries=min(self.max_retries, attempt),
            prompt_tokens=None,
            cached_input_tokens=None,
            completion_tokens=None,
            total_tokens=None,
            api_cost=None,
            request_id=request_id,
            error=last_error[:500],
        )
        return None, asdict(metrics)
