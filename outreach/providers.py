from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Protocol


class ProviderUnavailableError(RuntimeError):
    pass


class StructuredGenerationProvider(Protocol):
    name: str

    async def generate(self, *, purpose: str, context: dict) -> dict: ...


class SpeechProvider(Protocol):
    name: str

    async def transcribe(self, audio: bytes) -> str: ...

    async def synthesize(self, text: str) -> bytes: ...


@dataclass
class CircuitBreaker:
    """Small provider-neutral circuit breaker for bounded external calls."""

    failure_threshold: int = 3
    recovery_seconds: float = 30.0
    failures: int = 0
    opened_at: float | None = None

    async def execute(self, operation: Callable[[], Awaitable[dict]]) -> dict:
        now = time.monotonic()
        if self.opened_at is not None:
            if now - self.opened_at < self.recovery_seconds:
                raise ProviderUnavailableError("Provider circuit is open")
            self.opened_at = None
            self.failures = 0
        try:
            result = await operation()
        except Exception:
            self.failures += 1
            if self.failures >= self.failure_threshold:
                self.opened_at = time.monotonic()
            raise
        self.failures = 0
        self.opened_at = None
        return result


class DeterministicStructuredProvider:
    name = "deterministic"

    async def generate(self, *, purpose: str, context: dict) -> dict:
        return {
            "provider": self.name,
            "purpose": purpose,
            "validated": True,
            "result": context,
        }
