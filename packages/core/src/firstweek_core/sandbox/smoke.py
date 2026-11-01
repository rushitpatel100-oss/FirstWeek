"""Real jobs against the configured backend: `make sandbox-smoke`."""

import asyncio
import sys

from firstweek_core.config import get_settings
from firstweek_core.sandbox import SandboxJob, get_runner


async def main() -> int:
    runner = get_runner(get_settings())
    failures: list[str] = []

    hello = await runner.run(
        SandboxJob(
            files={"t.py": "print(sum(range(10)))\nopen('out.txt','w').write('done')"},
            command=["python", "t.py"],
            collect=["out.txt"],
        )
    )
    print("hello:", hello.exit_code, hello.stdout.strip(), hello.files)
    if not (hello.ok and hello.stdout.strip() == "45" and hello.files == {"out.txt": "done"}):
        failures.append("a plain job did not return its output and file")

    loop = await runner.run(
        SandboxJob(files={"t.py": "while True: pass"}, command=["python", "t.py"], timeout_s=3)
    )
    print("timeout:", loop.timed_out, f"{loop.duration_s:.1f}s")
    if not loop.timed_out:
        failures.append("an endless loop was not stopped")

    net = await runner.run(
        SandboxJob(
            files={
                "t.py": "import urllib.request as u\nu.urlopen('https://example.com', timeout=3)"
            },
            command=["python", "t.py"],
            timeout_s=20,
        )
    )
    print("network:", net.exit_code, (net.stderr.strip().splitlines() or [""])[-1][:120])
    if net.ok:
        failures.append("a job without network reached the internet")

    flood = await runner.run(
        SandboxJob(files={"t.py": "print('x' * 500000)"}, command=["python", "t.py"])
    )
    print("flood:", len(flood.stdout), flood.truncated)
    if not flood.truncated:
        failures.append("huge output was not cut")

    for failure in failures:
        print("FAIL:", failure)
    print("sandbox OK" if not failures else "sandbox NOT OK")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
