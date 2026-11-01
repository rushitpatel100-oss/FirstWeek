"""Local Docker backend: one throwaway container per job, locked down.

The container has no network (unless the job asks), no capabilities, a read-only root, a
memory, CPU and process limit, and runs as an unprivileged user. Only the job's files are
visible, in a temporary directory that is deleted afterwards. No environment is passed in.
"""

import asyncio
import os
import shutil
import tempfile
import time
import uuid
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from pathlib import Path

from firstweek_core.sandbox.runner import JobResult, SandboxJob, clip

WORKDIR = "/work"
UNPRIVILEGED = "65534:65534"  # nobody


@dataclass(frozen=True)
class ProcessOutput:
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool


# Runs an argument list and waits at most `limit_s` seconds. Replaced in tests.
ProcessFn = Callable[[list[str], float], Awaitable[ProcessOutput]]


async def run_process(argv: list[str], limit_s: float) -> ProcessOutput:
    proc = await asyncio.create_subprocess_exec(
        *argv,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        stdin=asyncio.subprocess.DEVNULL,
        env={"PATH": os.environ.get("PATH", "/usr/bin:/bin")},  # not the caller's secrets
    )
    try:
        out, err = await asyncio.wait_for(proc.communicate(), limit_s)
    except TimeoutError:
        proc.kill()
        await proc.wait()
        return ProcessOutput(-1, "", "", True)
    return ProcessOutput(
        proc.returncode if proc.returncode is not None else -1,
        out.decode(errors="replace"),
        err.decode(errors="replace"),
        False,
    )


class DockerRunner:
    def __init__(
        self,
        image: str = "firstweek-sandbox:py",
        *,
        memory: str = "512m",
        cpus: str = "1",
        pids: int = 256,
        process: ProcessFn = run_process,
    ) -> None:
        self.image, self.memory, self.cpus, self.pids = image, memory, cpus, pids
        self._process = process

    def command_line(self, job: SandboxJob, name: str, host_dir: Path) -> list[str]:
        return [
            "docker", "run", "--rm", "--name", name,
            "--network", "bridge" if job.network else "none",
            "--cap-drop", "ALL",
            "--security-opt", "no-new-privileges",
            "--read-only", "--tmpfs", "/tmp:rw,size=64m",
            "--memory", self.memory, "--memory-swap", self.memory,
            "--cpus", self.cpus, "--pids-limit", str(self.pids),
            "--user", UNPRIVILEGED,
            "-v", f"{host_dir}:{WORKDIR}:rw", "-w", WORKDIR,
            self.image, *job.command,
        ]  # fmt: skip

    async def run(self, job: SandboxJob) -> JobResult:
        host_dir = Path(await asyncio.to_thread(tempfile.mkdtemp, prefix="firstweek-job-"))
        name = f"firstweek-{uuid.uuid4().hex[:12]}"
        started = time.monotonic()
        try:
            await asyncio.to_thread(_write_files, host_dir, job.files)
            output = await self._process(self.command_line(job, name, host_dir), job.timeout_s)
            if output.timed_out:
                await self._process(["docker", "kill", name], 10.0)  # stop what is still running
            files = await asyncio.to_thread(_read_files, host_dir, job.collect)
        finally:
            await asyncio.to_thread(shutil.rmtree, host_dir, ignore_errors=True)
        stdout, cut_out = clip(output.stdout)
        stderr, cut_err = clip(output.stderr)
        return JobResult(
            exit_code=output.exit_code,
            stdout=stdout,
            stderr=stderr,
            timed_out=output.timed_out,
            truncated=cut_out or cut_err,
            files=files,
            duration_s=time.monotonic() - started,
        )


def _write_files(host_dir: Path, files: dict[str, str]) -> None:
    host_dir.chmod(0o777)  # the container user is not us
    for path, text in files.items():
        target = host_dir / path
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(text)
    for folder in [p for p in host_dir.rglob("*") if p.is_dir()]:
        folder.chmod(0o777)


def _read_files(host_dir: Path, paths: list[str]) -> dict[str, str]:
    """Reads files the job wrote. A symlink pointing outside the job directory is ignored: the
    job could otherwise make us read any file on this machine."""
    root = host_dir.resolve()
    found: dict[str, str] = {}
    for path in paths:
        target = (host_dir / path).resolve()
        if target.is_relative_to(root) and target.is_file():
            found[path] = target.read_text(errors="replace")
    return found
