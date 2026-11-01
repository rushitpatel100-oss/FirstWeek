# ruff: noqa: ASYNC240  (tests may touch the temp directory directly)
import sys
import types
from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from firstweek_core.config import Settings
from firstweek_core.sandbox import DockerRunner, E2BRunner, SandboxJob, get_runner
from firstweek_core.sandbox.docker import ProcessOutput
from firstweek_core.sandbox.runner import MAX_OUTPUT_CHARS, clip


def job(**kw: Any) -> SandboxJob:
    return SandboxJob(command=["python", "t.py"], **kw)


@pytest.mark.parametrize(
    "path", ["/etc/passwd", "../x.py", "a/../../x", "~/x", "", ".", "a\\b", "a//b", "./a"]
)
def test_unsafe_paths_are_refused(path: str) -> None:
    with pytest.raises(ValidationError):
        job(files={path: "x"})
    with pytest.raises(ValidationError):
        job(collect=[path])


def test_job_limits() -> None:
    with pytest.raises(ValidationError):
        SandboxJob(command=[])
    with pytest.raises(ValidationError):
        SandboxJob(command=[" "])
    with pytest.raises(ValidationError):
        job(timeout_s=0)
    with pytest.raises(ValidationError):
        job(timeout_s=301)
    with pytest.raises(ValidationError):
        job(files={f"f{i}.py": "" for i in range(201)})
    with pytest.raises(ValidationError):
        job(files={"big.txt": "x" * 1_000_001})
    assert job(files={"pkg/a.py": "x"}).network is False


def test_a_job_has_no_way_to_carry_secrets() -> None:
    assert "env" not in SandboxJob.model_fields
    with pytest.raises(ValidationError):
        SandboxJob.model_validate({"command": ["ls"], "env": {"KEY": "v"}})


def test_clip_keeps_the_tail() -> None:
    text, cut = clip("a" * 10 + "z" * MAX_OUTPUT_CHARS)
    assert cut and text.endswith("z") and "a" not in text.split("\n", 1)[1]
    assert clip("short") == ("short", False)


class FakeProcess:
    def __init__(self, output: ProcessOutput) -> None:
        self.output, self.calls = output, []  # type: ignore[var-annotated]
        self.seen_files: dict[str, str] = {}

    async def __call__(self, argv: list[str], limit_s: float) -> ProcessOutput:
        self.calls.append((argv, limit_s))
        if argv[:2] == ["docker", "run"]:
            mount = argv[argv.index("-v") + 1].split(":")[0]
            for p in Path(mount).rglob("*"):
                if p.is_file():
                    self.seen_files[str(p.relative_to(mount))] = p.read_text()
            (Path(mount) / "out.txt").write_text("result")
            (Path(mount) / "link").symlink_to("/etc/hostname")
        return self.output


async def test_docker_command_is_locked_down_and_files_round_trip() -> None:
    fake = FakeProcess(ProcessOutput(0, "hi", "", False))
    result = await DockerRunner("img:1", process=fake).run(
        job(files={"t.py": "print(1)", "pkg/m.py": "y"}, collect=["out.txt", "link", "nope"])
    )
    argv, limit = fake.calls[0]
    joined = " ".join(argv)
    for flag in ["--network none", "--cap-drop ALL", "no-new-privileges", "--read-only",
                 "--pids-limit", "--memory", "--user 65534:65534"]:  # fmt: skip
        assert flag in joined
    assert "-e " not in joined and "--env" not in joined and "--privileged" not in joined
    assert argv[-3:] == ["img:1", "python", "t.py"] and limit == 60.0
    assert fake.seen_files == {"t.py": "print(1)", "pkg/m.py": "y"}
    assert result.ok and result.stdout == "hi"
    assert result.files == {"out.txt": "result"}  # the symlink out of the job is ignored


async def test_docker_network_only_when_asked() -> None:
    fake = FakeProcess(ProcessOutput(0, "", "", False))
    await DockerRunner(process=fake).run(job(network=True))
    assert "--network bridge" in " ".join(fake.calls[0][0])


async def test_timeout_kills_the_container_and_cleans_up() -> None:
    fake = FakeProcess(ProcessOutput(-1, "", "", True))
    result = await DockerRunner(process=fake).run(job())
    run_argv = fake.calls[0][0]
    assert result.timed_out and not result.ok
    assert fake.calls[1][0] == ["docker", "kill", run_argv[run_argv.index("--name") + 1]]
    mount = run_argv[run_argv.index("-v") + 1].split(":")[0]
    assert not Path(mount).exists()


async def test_long_output_is_cut() -> None:
    fake = FakeProcess(ProcessOutput(1, "x" * (MAX_OUTPUT_CHARS + 5), "boom", False))
    result = await DockerRunner(process=fake).run(job())
    assert result.truncated and result.exit_code == 1 and result.stderr == "boom"


class FakeSandbox:
    created: dict[str, Any] = {}
    instance: "FakeSandbox | None" = None

    def __init__(self) -> None:
        self.written: dict[str, str] = {}
        self.ran: list[tuple[str, Any]] = []
        self.killed = False
        self.mode = "ok"
        self.files = self
        self.commands = self

    @classmethod
    async def create(cls, **kw: Any) -> "FakeSandbox":
        cls.created = kw
        cls.instance = cls()
        return cls.instance

    async def write(self, path: str, data: str) -> None:
        self.written[path] = data

    async def read(self, path: str) -> str:
        if path.endswith("missing"):
            raise FileNotFoundError(path)
        return "content"

    async def run(self, cmd: str, **kw: Any) -> Any:
        self.ran.append((cmd, kw))
        fake_module = sys.modules["e2b"]
        mode = FakeSandbox.mode_next
        if mode == "fail":
            raise fake_module.CommandExitException(status_code=3, stdout="o", stderr="e")
        if mode == "timeout":
            raise fake_module.TimeoutException("slow")
        return types.SimpleNamespace(stdout="fine", stderr="")

    async def kill(self) -> None:
        self.killed = True

    mode_next = "ok"


@pytest.fixture
def fake_e2b(monkeypatch: pytest.MonkeyPatch) -> type[FakeSandbox]:
    class CommandExitException(Exception):  # noqa: N818
        def __init__(self, status_code: int, stdout: str, stderr: str) -> None:
            self.status_code, self.stdout, self.stderr = status_code, stdout, stderr

    class TimeoutException(Exception):  # noqa: N818
        pass

    module = types.ModuleType("e2b")
    module.AsyncSandbox = FakeSandbox  # type: ignore[attr-defined]
    module.CommandExitException = CommandExitException  # type: ignore[attr-defined]
    module.TimeoutException = TimeoutException  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "e2b", module)
    FakeSandbox.mode_next = "ok"
    return FakeSandbox


async def test_e2b_runs_the_job_and_always_kills(fake_e2b: type[FakeSandbox]) -> None:
    result = await E2BRunner("key").run(
        job(files={"t.py": "print(1)"}, collect=["a.txt", "missing"], timeout_s=30)
    )
    box = fake_e2b.instance
    assert box is not None and box.killed
    assert result.ok and result.stdout == "fine" and result.files == {"a.txt": "content"}
    assert box.written == {"/home/user/work/t.py": "print(1)"}
    assert box.ran[0][0] == "python t.py" and box.ran[0][1]["timeout"] == 30
    assert fake_e2b.created["allow_internet_access"] is False
    assert "envs" not in fake_e2b.created and "envs" not in box.ran[0][1]


async def test_e2b_failure_and_timeout(fake_e2b: type[FakeSandbox]) -> None:
    fake_e2b.mode_next = "fail"
    failed = await E2BRunner("key").run(job())
    assert failed.exit_code == 3 and failed.stdout == "o" and failed.stderr == "e"
    fake_e2b.mode_next = "timeout"
    slow = await E2BRunner("key").run(job())
    assert slow.timed_out and not slow.ok
    assert fake_e2b.instance is not None and fake_e2b.instance.killed


def test_factory_picks_the_backend() -> None:
    base: dict[str, Any] = {"_env_file": None}
    assert isinstance(get_runner(Settings(**base)), DockerRunner)
    with pytest.raises(RuntimeError, match="E2B_API_KEY"):
        get_runner(Settings(sandbox_backend="e2b", **base))
    assert isinstance(
        get_runner(Settings(sandbox_backend="e2b", e2b_api_key="k", **base)),
        E2BRunner,
    )
