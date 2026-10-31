# 0004. A managed sandbox (E2B) behind our own SandboxRunner interface

- Status: accepted (implementation in M3)
- Date: 2026-10-30

## Context

FirstWeek runs untrusted code: user submissions, generated starter repos and reference solutions. Running it safely needs real isolation (no network, resource and time limits, throwaway file systems). Building that isolation well is a project in itself.

## Decision

- Code runs in **E2B** cloud sandboxes, which provide isolated micro-VMs.
- All callers use a small `SandboxRunner` interface (run a command, read and write files, enforce timeouts). An E2B adapter is used in production and a local Docker adapter in development and tests.
- Each run is a short job. Files live outside the sandbox (object storage), so the free tier's 1-hour session limit never matters.

## Consequences

- Safety comes from a specialised provider rather than home-made isolation.
- Swapping to self-hosted Firecracker or gVisor later only means a new adapter.
- The free tier's one-time credit is reserved for demos and evals; day-to-day development uses the Docker adapter.

## Alternatives considered

- Running code in our own containers from day one: weaker isolation unless done with great care.
- No code execution (document tasks only): far less convincing for technical roles.
