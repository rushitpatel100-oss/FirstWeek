"""Code sandbox: run a short job in isolation (ADR 0017)."""

from firstweek_core.config import Settings
from firstweek_core.sandbox.docker import DockerRunner
from firstweek_core.sandbox.e2b import E2BRunner
from firstweek_core.sandbox.runner import JobResult, SandboxJob, SandboxRunner


def get_runner(settings: Settings) -> SandboxRunner:
    """The backend the settings choose: Docker in development, E2B for demos and evals."""
    if settings.sandbox_backend == "e2b":
        if settings.e2b_api_key is None:
            raise RuntimeError("Set E2B_API_KEY in .env to use the E2B sandbox.")
        return E2BRunner(settings.e2b_api_key.get_secret_value())
    return DockerRunner(settings.sandbox_image)


__all__ = ["DockerRunner", "E2BRunner", "JobResult", "SandboxJob", "SandboxRunner", "get_runner"]
