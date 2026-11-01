"""The sandbox contract: run one short job in isolation and get its result back (ADR 0017).

A job is a set of text files, one command and a time limit. There is deliberately no way to
pass environment variables, secrets or a shell string: the sandbox never receives a key, and
the command is an argument list, so nothing is interpreted by a shell. Every backend returns
the same `JobResult`.
"""

import posixpath
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

MAX_FILES = 200
MAX_TOTAL_BYTES = 1_000_000
MAX_TIMEOUT_S = 300.0
MAX_OUTPUT_CHARS = 20_000  # per stream; the tail is what explains a failure, so keep that


def check_relative_path(path: str) -> str:
    """A file path inside the sandbox's working directory: relative, no '..', no oddities."""
    clean = posixpath.normpath(path)
    if (
        not path
        or path.startswith(("/", "~"))
        or "\\" in path
        or "\x00" in path
        or clean == "."
        or clean.split("/")[0] == ".."
        or clean != path
    ):
        raise ValueError(f"not a plain relative path: {path!r}")
    return path


class SandboxJob(BaseModel):
    model_config = ConfigDict(extra="forbid")  # an unknown field such as `env` is an error

    files: dict[str, str] = Field(default_factory=dict, description="Relative path -> text.")
    command: list[str] = Field(min_length=1, description="The program and its arguments.")
    timeout_s: float = Field(default=60.0, gt=0, le=MAX_TIMEOUT_S)
    collect: list[str] = Field(
        default_factory=list, description="Files to read back after the command ends."
    )
    network: bool = Field(default=False, description="Internet access. Off unless a job needs it.")

    @field_validator("files")
    @classmethod
    def _files_are_safe(cls, files: dict[str, str]) -> dict[str, str]:
        if len(files) > MAX_FILES:
            raise ValueError(f"at most {MAX_FILES} files")
        for path in files:
            check_relative_path(path)
        if sum(len(text.encode()) for text in files.values()) > MAX_TOTAL_BYTES:
            raise ValueError("files are too large in total")
        return files

    @field_validator("collect")
    @classmethod
    def _collect_paths_are_safe(cls, paths: list[str]) -> list[str]:
        for path in paths:
            check_relative_path(path)
        return paths

    @model_validator(mode="after")
    def _command_is_not_empty(self) -> "SandboxJob":
        if not self.command[0].strip():
            raise ValueError("the command is empty")
        return self


class JobResult(BaseModel):
    exit_code: int
    stdout: str
    stderr: str
    timed_out: bool = False
    truncated: bool = Field(default=False, description="Output was cut at the limit.")
    files: dict[str, str] = Field(default_factory=dict, description="The collected files.")
    duration_s: float = Field(ge=0)

    @property
    def ok(self) -> bool:
        return self.exit_code == 0 and not self.timed_out


def clip(text: str) -> tuple[str, bool]:
    """Keeps the end of a long output, where failures are explained."""
    if len(text) <= MAX_OUTPUT_CHARS:
        return text, False
    return "[... earlier output cut ...]\n" + text[-MAX_OUTPUT_CHARS:], True


class SandboxRunner(Protocol):
    async def run(self, job: SandboxJob) -> JobResult: ...
