"""One dev run, driven by the worker: issue in, pull request out.

1. Clone the repository into a private folder, with the token.
2. Clone that into the shared run folder, without the token, on the agent's branch.
3. Start the run container, which runs dev_agent against the run folder.
4. Fetch the agent's commit from out.bundle into the private clone.
5. Refuse protected paths, push the branch, open the pull request.

The agent's working copy is never used for push: its hooks and git config are
the agent's to change, so the worker only reads the bundle it produced.
"""

import json
import logging
import re
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import asdict
from pathlib import Path
from typing import Any

from signal_loop_agents.config import WorkerSettings
from signal_loop_agents.dev_agent import Result, Task
from signal_loop_agents.github import authed_remote_url, create_pull_request
from signal_loop_agents.inbox import InboxEvent

log = logging.getLogger("signal_loop_agents.dev_run")

BASE_BRANCH = "main"
PROTECTED_PATHS = ("agents/", ".github/", ".claude/", "compose.yaml")

RunContainer = Callable[[Path], int]
OpenPullRequest = Callable[..., str]


class DevRunError(RuntimeError):
    pass


def get_task_from_event(event: InboxEvent) -> Task:
    data: dict[str, Any] = event.payload.get("data") or {}
    title = data.get("title") or "Untitled issue"
    slug = (
        re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:40].strip("-") or "change"
    )
    return Task(
        issue_id=event.issue_id or str(event.id),
        title=title,
        description=data.get("description") or "",
        branch=f"agent/{event.issue_id}-{slug}",
    )


def git(repo: Path, *args: str) -> str:
    # Hooks are off for every git call the worker makes.
    return subprocess.run(
        ["git", "-c", "core.hooksPath=/dev/null", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
    ).stdout


def touched_protected_paths(files: list[str]) -> list[str]:
    return [f for f in files if f == "compose.yaml" or f.startswith(PROTECTED_PATHS)]


def run_dev_task(
    event: InboxEvent,
    settings: WorkerSettings,
    *,
    run_container: RunContainer,
    open_pull_request: OpenPullRequest,
    remote_url: str | None = None,
) -> str:
    task = get_task_from_event(event)
    remote = remote_url or authed_remote_url(
        settings.github_token, settings.github_repo
    )
    private = Path(settings.work_dir) / f"task-{event.id}"
    run_dir = Path(settings.runs_dir) / f"task-{event.id}"
    for folder in (private, run_dir):
        shutil.rmtree(folder, ignore_errors=True)
    private.parent.mkdir(parents=True, exist_ok=True)
    run_dir.mkdir(parents=True)

    try:
        subprocess.run(
            ["git", "clone", "--quiet", "--branch", BASE_BRANCH, remote, str(private)],
            check=True,
            capture_output=True,
        )
        git(run_dir, "clone", "--quiet", str(private), "repo")
        git(run_dir / "repo", "checkout", "--quiet", "-b", task.branch)
        (run_dir / "task.json").write_text(json.dumps(asdict(task)))

        log.info("starting dev run for %s on %s", task.issue_id, task.branch)
        exit_code = run_container(run_dir)
        result = read_result(run_dir)
        if exit_code != 0 or not result.ok:
            raise DevRunError(result.error or f"run container exited with {exit_code}")
        log.info("dev agent done: turns=%s cost=$%.2f", result.turns, result.cost_usd)

        git(
            private,
            "fetch",
            "--quiet",
            str(run_dir / "out.bundle"),
            f"{task.branch}:{task.branch}",
        )
        changed = git(
            private, "diff", "--name-only", f"{BASE_BRANCH}..{task.branch}"
        ).split()
        if not changed:
            raise DevRunError("agent commit has no changes")
        if blocked := touched_protected_paths(changed):
            raise DevRunError(f"agent changed protected paths: {', '.join(blocked)}")

        git(private, "push", "--quiet", remote, f"{task.branch}:{task.branch}")
        url = open_pull_request(
            head=task.branch,
            base=BASE_BRANCH,
            title=f"{task.issue_id}: {task.title}",
            body=pull_request_body(task, result),
        )
        log.info("opened pull request %s for %s", url, task.issue_id)
        return url
    finally:
        shutil.rmtree(private, ignore_errors=True)
        shutil.rmtree(run_dir, ignore_errors=True)


def read_result(run_dir: Path) -> Result:
    try:
        raw = json.loads((run_dir / "result.json").read_text())
        return Result(
            ok=raw.get("ok") is True,
            summary=str(raw.get("summary", ""))[:20_000],
            error=str(raw.get("error", ""))[:2_000],
            turns=int(raw.get("turns", 0)),
            cost_usd=float(raw.get("cost_usd", 0.0)),
        )
    except (OSError, ValueError, TypeError) as exc:
        return Result(ok=False, error=f"unreadable result.json: {exc}")


def pull_request_body(task: Task, result: Result) -> str:
    return (
        f"{result.summary.strip() or 'No summary from the agent.'}\n\n"
        f"---\nLinear issue: {task.issue_id}. "
        f"Agent used {result.turns} turns, about ${result.cost_usd:.2f}.\n\n"
        "🤖 Opened by the Signal Loop dev agent."
    )


def docker_run_container(settings: WorkerSettings) -> RunContainer:
    """Runs dev_agent in a fresh container from the agents image, then removes it."""

    def run(run_dir: Path) -> int:
        import docker

        client = docker.from_env()
        container = client.containers.run(
            settings.run_image,
            [".venv/bin/python", "-m", "signal_loop_agents.dev_agent", str(run_dir)],
            environment=settings.agent_env,
            volumes={settings.runs_volume: {"bind": settings.runs_dir, "mode": "rw"}},
            detach=True,
        )
        try:
            for line in container.logs(stream=True, follow=True):
                log.info("[run] %s", line.decode(errors="replace").rstrip())
            return int(container.wait()["StatusCode"])
        finally:
            container.remove(force=True)

    return run


def github_pull_request_opener(settings: WorkerSettings) -> OpenPullRequest:
    def open_pr(**kwargs: str) -> str:
        return create_pull_request(
            settings.github_token, settings.github_repo, **kwargs
        )

    return open_pr
