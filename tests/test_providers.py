import pytest

from outreach.providers import (
    CircuitBreaker,
    DeterministicStructuredProvider,
    ProviderUnavailableError,
)


async def test_deterministic_provider_returns_traceable_shape() -> None:
    result = await DeterministicStructuredProvider().generate(
        purpose="clinical_triage",
        context={"classification": "routine"},
    )

    assert result["provider"] == "deterministic"
    assert result["purpose"] == "clinical_triage"
    assert result["validated"] is True


async def test_circuit_breaker_opens_and_recovers() -> None:
    breaker = CircuitBreaker(failure_threshold=2, recovery_seconds=10)

    async def fail() -> dict:
        raise TimeoutError

    with pytest.raises(TimeoutError):
        await breaker.execute(fail)
    with pytest.raises(TimeoutError):
        await breaker.execute(fail)
    with pytest.raises(ProviderUnavailableError):
        await breaker.execute(fail)

    assert breaker.opened_at is not None
    breaker.opened_at -= 11

    async def succeed() -> dict:
        return {"ok": True}

    assert await breaker.execute(succeed) == {"ok": True}
