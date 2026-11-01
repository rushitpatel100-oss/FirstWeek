"""E2B backend: the same job, run in a hosted sandbox (for demos and evals).

E2B sessions last at most an hour on the free tier, so every job creates a sandbox, runs once
and kills it; files live outside, in the job. No environment variables are sent."""

import shlex
import time
from typing import Any

from firstweek_core.sandbox.runner import JobResult, SandboxJob, clip

WORKDIR = "/home/user/work"


class E2BRunner:
    def __init__(self, api_key: str, *, template: str | None = None) -> None:
        self._api_key, self._template = api_key, template

    async def run(self, job: SandboxJob) -> JobResult:
        from e2b import AsyncSandbox, CommandExitException, TimeoutException

        started = time.monotonic()
        sandbox: Any = await AsyncSandbox.create(
            template=self._template,
            timeout=int(job.timeout_s) + 60,  # the sandbox outlives the command, then is killed
            allow_internet_access=job.network,
            api_key=self._api_key,
        )
        exit_code, stdout, stderr, timed_out = 0, "", "", False
        files: dict[str, str] = {}
        try:
            for path, text in job.files.items():
                await sandbox.files.write(f"{WORKDIR}/{path}", text)
            try:
                result = await sandbox.commands.run(
                    shlex.join(job.command), cwd=WORKDIR, timeout=job.timeout_s
                )
                stdout, stderr = result.stdout, result.stderr
            except CommandExitException as exc:
                exit_code = exc.status_code or 1
                stdout = str(getattr(exc, "stdout", ""))
                stderr = str(getattr(exc, "stderr", ""))
            except TimeoutException:
                exit_code, timed_out = -1, True
            for path in job.collect:
                try:
                    files[path] = await sandbox.files.read(f"{WORKDIR}/{path}")
                except Exception:  # a file the job did not write is simply absent
                    continue
        finally:
            await sandbox.kill()
        out, cut_out = clip(stdout)
        err, cut_err = clip(stderr)
        return JobResult(
            exit_code=exit_code,
            stdout=out,
            stderr=err,
            timed_out=timed_out,
            truncated=cut_out or cut_err,
            files=files,
            duration_s=time.monotonic() - started,
        )
