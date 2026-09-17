from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time

import httpx


async def run(base_url: str, requests: int, concurrency: int) -> dict:
    limits = httpx.Limits(max_connections=concurrency)
    timeout = httpx.Timeout(10)
    async with httpx.AsyncClient(limits=limits, timeout=timeout) as client:
        token_response = await client.post(
            f"{base_url}/api/v1/auth/demo-token",
            json={"hospital_slug": "mercy-general", "role": "hospital_admin"},
        )
        token_response.raise_for_status()
        headers = {"Authorization": f"Bearer {token_response.json()['access_token']}"}
        semaphore = asyncio.Semaphore(concurrency)

        async def request_once() -> tuple[float, int]:
            async with semaphore:
                started = time.perf_counter()
                response = await client.get(
                    f"{base_url}/api/v1/simulation",
                    headers=headers,
                )
                return (time.perf_counter() - started) * 1000, response.status_code

        results = await asyncio.gather(*(request_once() for _ in range(requests)))
    latencies = sorted(item[0] for item in results)
    percentile_index = max(0, round(len(latencies) * 0.95) - 1)
    return {
        "requests": requests,
        "concurrency": concurrency,
        "successful": sum(status == 200 for _, status in results),
        "failed": sum(status != 200 for _, status in results),
        "latency_ms": {
            "average": round(statistics.mean(latencies), 2),
            "p95": round(latencies[percentile_index], 2),
            "maximum": round(max(latencies), 2),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Synthetic read-only API load check")
    parser.add_argument(
        "--base-url",
        default="https://multi-hospital-outreach-production.up.railway.app",
    )
    parser.add_argument("--requests", type=int, default=30)
    parser.add_argument("--concurrency", type=int, default=5)
    args = parser.parse_args()
    report = asyncio.run(run(args.base_url.rstrip("/"), args.requests, args.concurrency))
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
