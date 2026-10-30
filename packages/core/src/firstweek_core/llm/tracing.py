"""Tracing for model calls. Langfuse when keys are set, otherwise a no-op.

The gateway only depends on the small Tracer protocol, so tests use a fake and
the app keeps working with tracing switched off.
"""

from collections.abc import Iterator
from contextlib import AbstractContextManager, contextmanager
from decimal import Decimal
from typing import Any, Protocol


class GenerationHandle(Protocol):
    @property
    def trace_id(self) -> str | None: ...

    def finish(
        self,
        *,
        output: Any,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        error: str | None = None,
    ) -> None: ...


class Tracer(Protocol):
    def generation(
        self, *, name: str, model: str, input: Any, metadata: dict[str, Any]
    ) -> AbstractContextManager[GenerationHandle]: ...

    def flush(self) -> None: ...


class _NoopHandle:
    trace_id: str | None = None

    def finish(self, **_: Any) -> None:
        return None


class NoopTracer:
    @contextmanager
    def generation(
        self, *, name: str, model: str, input: Any, metadata: dict[str, Any]
    ) -> Iterator[GenerationHandle]:
        yield _NoopHandle()

    def flush(self) -> None:
        return None


class _LangfuseHandle:
    def __init__(self, generation: Any) -> None:
        self._generation = generation

    @property
    def trace_id(self) -> str | None:
        value = getattr(self._generation, "trace_id", None)
        return str(value) if value is not None else None

    def finish(
        self,
        *,
        output: Any,
        tokens_in: int,
        tokens_out: int,
        cost_usd: Decimal,
        error: str | None = None,
    ) -> None:
        # We record our own cost so Langfuse shows exactly what the budget counted.
        self._generation.update(
            output=output,
            usage_details={"input": tokens_in, "output": tokens_out},
            cost_details={"total": float(cost_usd)},
            level="ERROR" if error else "DEFAULT",
            status_message=error,
        )


class LangfuseTracer:
    """Uses the Langfuse SDK's own environment variables (LANGFUSE_PUBLIC_KEY and so on)."""

    def __init__(self) -> None:
        from langfuse import get_client

        self._client = get_client()

    @contextmanager
    def generation(
        self, *, name: str, model: str, input: Any, metadata: dict[str, Any]
    ) -> Iterator[GenerationHandle]:
        with self._client.start_as_current_observation(
            as_type="generation", name=name, model=model, input=input, metadata=metadata
        ) as generation:
            yield _LangfuseHandle(generation)

    def flush(self) -> None:
        self._client.flush()


def default_tracer(enabled: bool) -> Tracer:
    return LangfuseTracer() if enabled else NoopTracer()
