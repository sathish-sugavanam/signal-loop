import json
import subprocess
from pathlib import Path

import pytest

from signal_loop_agents.config import WorkerSettings
from signal_loop_agents.dev_agent import Result, Task, commit_and_bundle, write_result
from signal_loop_agents.dev_run import (
    DevRunError,
    run_dev_task,
    task_from_event,
    touched_protected_paths,
)
from signal_loop_agents.inbox import InboxEvent


def git(cwd: Path, *args: str) -> str:
    return subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@t", *args],
        cwd=cwd, check=True, capture_output=True, text=True,
    ).stdout


def event(title: str = "Add CSV export!", issue_id: str = "SIG-7") -> InboxEvent:
    return InboxEvent(
        id=42,
        delivery_id="d-1",
        action="update",
        issue_id=issue_id,
        payload={"data": {"title": title, "description": "Export rows as CSV."}},
        attempts=1,
    )


@pytest.fixture
def remote(tmp_path) -> Path:
    """A bare repo standing in for GitHub, with one commit on main."""
    bare = tmp_path / "remote.git"
    git(tmp_path, "init", "--quiet", "--bare", "--initial-branch=main", str(bare))
    seed = tmp_path / "seed"
    git(tmp_path, "clone", "--quiet", str(bare), str(seed))
    (seed / "app.py").write_text("print('hi')\n")
    git(seed, "add", "-A")
    git(seed, "commit", "--quiet", "-m", "init")
    git(seed, "push", "--quiet", "origin", "HEAD:main")
    return bare


@pytest.fixture
def settings(tmp_path) -> WorkerSettings:
    return WorkerSettings(
        database_url="unused",
        broker_url="memory://",
        runs_dir=str(tmp_path / "runs"),
        work_dir=str(tmp_path / "work"),
    )


def fake_agent(edit: dict[str, str]):
    """Stands in for the run container: edits files, then commits like dev_agent does."""

    def run(run_dir: Path) -> int:
        task = Task(**json.loads((run_dir / "task.json").read_text()))
        assert "x-access-token" not in git(run_dir / "repo", "remote", "-v")
        for name, content in edit.items():
            path = run_dir / "repo" / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(content)
        ok = commit_and_bundle(run_dir, task)
        write_result(run_dir, Result(ok=ok, summary="Added export.", turns=3, cost_usd=0.5,
                                     error="" if ok else "agent made no changes"))
        return 0 if ok else 1

    return run


def test_task_from_event_builds_branch_from_key_and_title():
    task = task_from_event(event())
    assert (task.issue_id, task.branch) == ("SIG-7", "agent/SIG-7-add-csv-export")
    assert task.description == "Export rows as CSV."


def test_protected_paths():
    files = ["app.py", "agents/x.py", ".github/ci.yml", "compose.yaml", "docs/compose.yaml"]
    assert touched_protected_paths(files) == ["agents/x.py", ".github/ci.yml", "compose.yaml"]


def test_dev_run_pushes_branch_and_opens_pr(remote, settings):
    opened = {}

    def open_pr(**kwargs):
        opened.update(kwargs)
        return "https://github.com/o/r/pull/1"

    url = run_dev_task(
        event(), settings, run_container=fake_agent({"export.py": "def export(): ...\n"}),
        open_pull_request=open_pr, remote_url=str(remote),
    )
    assert url == "https://github.com/o/r/pull/1"
    branch = "agent/SIG-7-add-csv-export"
    assert git(remote, "show", f"{branch}:export.py") == "def export(): ...\n"
    assert git(remote, "log", "-1", "--format=%s", branch).strip() == "SIG-7: Add CSV export!"
    assert (opened["head"], opened["base"], opened["title"]) == (branch, "main", "SIG-7: Add CSV export!")
    assert "Added export." in opened["body"]
    assert not any(Path(settings.runs_dir).iterdir())  # run folder cleaned up


def test_dev_run_refuses_protected_paths(remote, settings):
    with pytest.raises(DevRunError, match="protected paths: agents/evil.py"):
        run_dev_task(
            event(), settings, run_container=fake_agent({"agents/evil.py": "x\n"}),
            open_pull_request=lambda **_: pytest.fail("must not open a PR"), remote_url=str(remote),
        )
    assert "agent/" not in git(remote, "branch", "--list")


def test_dev_run_fails_when_agent_changes_nothing(remote, settings):
    with pytest.raises(DevRunError, match="agent made no changes"):
        run_dev_task(
            event(), settings, run_container=fake_agent({}),
            open_pull_request=lambda **_: pytest.fail("must not open a PR"), remote_url=str(remote),
        )


def test_dev_run_fails_on_missing_result(remote, settings):
    with pytest.raises(DevRunError, match="unreadable result.json"):
        run_dev_task(
            event(), settings, run_container=lambda run_dir: 137,
            open_pull_request=lambda **_: pytest.fail("must not open a PR"), remote_url=str(remote),
        )
