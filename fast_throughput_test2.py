import asyncio
import time
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)) + "/backend")
from app.services.ai_service import ai_service

async def test_throughput():
    await ai_service.warm_up()
    print("Warmup complete.")
    N = 3
    start = time.time()
    tasks = []
    for i in range(N):
        tasks.append(ai_service.evaluate_answer_instant(
            question="What is Python?",
            ideal_answer="Python is an interpreted, high-level, general-purpose programming language.",
            candidate_answer="Python is a programming language used for scripting and backend development.",
            keywords=["interpreted", "high-level", "programming language"]
        ))
    results = await asyncio.gather(*tasks)
    end = time.time()
    elapsed = end - start
    print(f"==================================================")
    print(f"THROUGHPUT TEST RESULTS")
    print(f"==================================================")
    print(f"Completed {N} concurrent API evaluations in {elapsed:.2f} seconds.")
    print(f"Throughput: {N/elapsed:.2f} requests per second (RPS)")
    print(f"Average Latency: {(elapsed/N)*1000:.2f} ms per request")
    print(f"==================================================")

if __name__ == "__main__":
    asyncio.run(test_throughput())