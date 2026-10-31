# 0003. Every model call goes through one gateway

- Status: accepted
- Date: 2026-10-30

## Context

FirstWeek mixes models: a frontier model for blueprints and code review, a mid model for research, a small model for chat, and a judge from a different model family. Without one entry point, routing, cost control, retries and tracing would be scattered and inconsistent.

## Decision

`firstweek_core.llm.LLMGateway` is the only way to call a model. It:

- **Routes by tier** (`frontier`, `mid`, `small`, `judge`) to model strings set in configuration, using LiteLLM underneath.
- **Checks budgets before spending.** Each call is costed in the worst case (pessimistic token estimate plus `max_tokens`) against its budget scope, such as one simulation. If it does not fit, the call is refused, or downgraded to a cheaper tier when the caller allows it.
- **Uses our own price table** (`llm/pricing.py`), so new models are costed correctly even before libraries know them. Unknown models are priced like a top-tier model, so mistakes are on the safe side.
- **Validates structured output** against Pydantic contracts, sending validation errors back to the model for a bounded number of retries.
- **Traces** every call to Langfuse when keys are set, and **records** every call (tokens, cost, latency, prompt version, trace id) to the `llm_calls` table.

## Consequences

- A quality or cost change can always be traced to a model, a prompt version and a call.
- Tests replace the completion function with a fake, so they need no API keys and cost nothing.
- Changing a model is a configuration change, not a code change.

## Alternatives considered

- Calling provider SDKs directly: fastest to start, but no shared budgets or traces.
- An external gateway service: more to run, no benefit at this scale.
