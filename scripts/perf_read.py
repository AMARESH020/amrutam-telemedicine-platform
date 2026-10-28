import argparse
import asyncio
import math
import time
from collections import Counter

import httpx


def percentile(values, fraction):
    ordered = sorted(values)
    index = min(len(ordered) - 1, math.ceil(fraction * len(ordered)) - 1)
    return ordered[index]


async def run_benchmark(url, request_count, concurrency):
    semaphore = asyncio.Semaphore(concurrency)
    latencies_ms = []
    statuses = Counter()
    errors = 0

    async with httpx.AsyncClient(timeout=15.0) as client:
        async def send_request():
            nonlocal errors

            async with semaphore:
                started = time.perf_counter()

                try:
                    response = await client.get(url)
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies_ms.append(elapsed_ms)
                    statuses[response.status_code] += 1

                    if not 200 <= response.status_code < 300:
                        errors += 1
                except httpx.HTTPError:
                    elapsed_ms = (time.perf_counter() - started) * 1000
                    latencies_ms.append(elapsed_ms)
                    statuses["exception"] += 1
                    errors += 1

        wall_started = time.perf_counter()
        await asyncio.gather(
            *(send_request() for _ in range(request_count))
        )
        wall_seconds = time.perf_counter() - wall_started

    if not latencies_ms:
        print("No requests completed; check API connectivity.")
        return

    successful = sum(
        count for status, count in statuses.items()
        if isinstance(status, int) and 200 <= status < 300
    )

    print("\nREAD-ONLY API PERFORMANCE RESULTS")
    print(f"URL:                 {url}")
    print(f"Requests attempted:  {request_count}")
    print(f"Concurrency limit:   {concurrency}")
    print(f"Successful requests: {successful}")
    print(f"Failed requests:     {errors}")
    print(f"HTTP status counts:  {dict(statuses)}")
    print(f"Elapsed time:        {wall_seconds:.2f} seconds")
    print(f"Throughput:          {request_count / wall_seconds:.2f} requests/sec")
    print(f"p50 latency:         {percentile(latencies_ms, 0.50):.2f} ms")
    print(f"p95 latency:         {percentile(latencies_ms, 0.95):.2f} ms")
    print(f"p99 latency:         {percentile(latencies_ms, 0.99):.2f} ms")
    print(f"Max latency:         {max(latencies_ms):.2f} ms")


def main():
    parser = argparse.ArgumentParser(
        description="Read-only local API benchmark; performs HTTP GET requests only."
    )
    parser.add_argument(
        "--url",
        default="http://localhost:8000/api/v1/doctors",
    )
    parser.add_argument("--requests", type=int, default=300)
    parser.add_argument("--concurrency", type=int, default=20)
    args = parser.parse_args()

    if args.requests < 1 or args.concurrency < 1:
        parser.error("--requests and --concurrency must be positive")

    asyncio.run(
        run_benchmark(args.url, args.requests, args.concurrency)
    )


if __name__ == "__main__":
    main()
