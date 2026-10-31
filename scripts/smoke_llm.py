"""Make one real, traced model call through the gateway.

Needs ANTHROPIC_API_KEY in .env. With Langfuse keys set, the call also appears in Langfuse.
Run: make smoke-llm
"""

import asyncio

from firstweek_core.config import get_settings
from firstweek_core.llm import LLMGateway


async def main() -> None:
    settings = get_settings()
    if settings.anthropic_api_key is None:
        raise SystemExit("Set ANTHROPIC_API_KEY in .env first.")

    gateway = LLMGateway(settings=settings)
    result = await gateway.complete(
        purpose="smoke-test",
        messages=[{"role": "user", "content": "In one sentence, what does a GenAI Engineer do?"}],
        tier="small",
        budget_scope="smoke",
        budget_usd=0.05,
        max_tokens=120,
        prompt_version="smoke-v1",
    )
    gateway.flush()

    print(f"Model:   {result.model}")
    print(f"Reply:   {result.content}")
    print(f"Tokens:  {result.tokens_in} in / {result.tokens_out} out")
    print(f"Cost:    ${result.cost_usd:.6f}")
    print(f"Latency: {result.latency_ms} ms")
    if settings.tracing_enabled:
        print(f"Trace:   {result.trace_id} (open Langfuse to see it)")
    else:
        print("Trace:   tracing off (add Langfuse keys to .env to see calls in Langfuse)")


if __name__ == "__main__":
    asyncio.run(main())
