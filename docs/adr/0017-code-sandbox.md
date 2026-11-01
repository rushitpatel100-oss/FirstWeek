# ADR 0017: Code sandbox

Status: accepted (2026-11-01)

## Context

The simulation (M3) has people run code and tests, and the validation gate runs a project's reference solution to prove the planted issues are real. That code is untrusted: a person wrote it, or a model did. It must not reach our network, our files or our keys.

## Decision

- **One interface**: `SandboxRunner.run(job) -> JobResult` in `firstweek_core.sandbox`. A job is text files, one command (an argument list, never a shell string), a time limit (at most 300 s) and the files to read back. Each run is a short, separate job; state lives in the job's files, outside the sandbox.
- **No secrets by construction**: the job has no environment field, and unknown fields are errors. Docker is started with a minimal environment of its own. Nothing from `.env` can reach a job.
- **Rules enforced in code for every backend**: relative paths only (no `..`, no absolute, no backslashes), at most 200 files and 1 MB, no network unless the job asks, output cut to the last 20,000 characters per stream (`truncated` is set).
- **Docker backend (development)**: one throwaway container per job: no network, all capabilities dropped, no new privileges, read-only root plus a 64 MB `/tmp`, 512 MB memory (no swap), one CPU, 256 processes, user `nobody`, only the job's temporary directory mounted. On timeout the container is killed by name. Files the job wrote are read back only if they resolve inside the job directory, so a symlink cannot make us read a host file.
- **E2B backend (demos and evals)**: same job, same result; one sandbox per job, always killed. Needs `E2B_API_KEY`.
- **Python only, one fixed image** (`infra/docker/sandbox.Dockerfile`: Python 3.12, pytest, numpy, pandas) until a project needs more.
- `SANDBOX_BACKEND=docker|e2b` picks the backend; `make sandbox-image` builds the image; `make sandbox-smoke` runs real jobs (output, timeout, no network, output flood).

## Consequences

- Unit tests use a fake process and a fake E2B module, so CI needs neither Docker nor a key. The real isolation is checked by `make sandbox-smoke` on a machine with Docker.
- Docker is not a hard security boundary against a determined attacker (shared kernel). It is acceptable for development and our own reference solutions; anything run for the public should use E2B or gVisor/Firecracker before launch.
- A job cannot install packages (no network); anything needed goes into the image.
