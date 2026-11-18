"""The dev agent. Runs inside a throwaway run container, never in the worker.

    python -m signal_loop_agents.dev_agent /runs/<run>

The worker prepares the run folder: `task.json` with the issue, and `repo/`, a
clone already on the agent's branch. The agent edits `repo/`. This script then
commits the changes and leaves two files for the worker:
- `out.bundle`: the new commit, as a git bundle.
- `result.json`: whether it worked, the agent's summary, turns and cost.

The container holds only the Anthropic credential. No GitHub token, no database.
"""

import asyncio
import json
import os
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

DEFAULT_MODEL = "claude-opus-5-5"
MAX_TURNS = 80
MAX_BUDGET_USD = 5.0
TOOLS = ["Read", "Write", "Edit", "Glob", "Grep", "Bash"]
AUTHOR = [
    "-c",
    "user.name=Signal Loop Agent",
    "-c",
    "user.email=agent@signal-loop.invalid",
]

INSTRUCTIONS = """\
You are the dev agent for this repository. You implement one Linear issue end to end.

- Read the code before changing it, and follow the conventions you find.
- Keep the change focused on the issue. No unrelated refactors.
- Never modify agents/, .github/, .claude/ or compose.yaml. A change there fails the run.
- Do not commit, push or create branches. The harness commits your working tree for you.
- When you finish, reply with a short summary of what you changed and why. It becomes
  the pull request description.
"""


@dataclass(frozen=True)
class Task:
    issue_id: str
    title: str
    description: str
    branch: str


@dataclass(frozen=True)
class Result:
    ok: bool
    summary: str = ""
    error: str = ""
    turns: int = 0
    cost_usd: float = 0.0


def prompt_for(task: Task) -> str:
    return (
        f"Implement Linear issue {task.issue_id}: {task.title}\n\n"
        f"{task.description or '(The issue has no description.)'}"
    )


def git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, check=True, capture_output=True, text=True
    ).stdout


def commit_and_bundle(run_dir: Path, task: Task) -> bool:
    """Commits the agent's work and writes out.bundle. Returns False if nothing changed."""
    repo = run_dir / "repo"
    git(repo, "add", "-A")
    if not git(repo, "status", "--porcelain").strip():
        return False
    git(repo, *AUTHOR, "commit", "-m", f"{task.issue_id}: {task.title}")
    git(repo, "bundle", "create", str(run_dir / "out.bundle"), f"main..{task.branch}")
    return True


def write_result(run_dir: Path, result: Result) -> None:
    (run_dir / "result.json").write_text(json.dumps(asdict(result)))


async def run_agent(run_dir: Path, task: Task) -> Result:
    from claude_agent_sdk import ClaudeAgentOptions, ResultMessage, query

    model = os.environ.get("DEV_AGENT_MODEL") or DEFAULT_MODEL
    options = ClaudeAgentOptions(
        cwd=str(run_dir / "repo"),
        model=model,
        env={
            name: model
            for name in (
                "ANTHROPIC_DEFAULT_OPUS_MODEL",
                "ANTHROPIC_DEFAULT_SONNET_MODEL",
                "ANTHROPIC_DEFAULT_HAIKU_MODEL",
                "CLAUDE_CODE_SUBAGENT_MODEL",
            )
        },
        system_prompt={
            "type": "preset",
            "preset": "claude_code",
            "append": INSTRUCTIONS,
        },
        allowed_tools=TOOLS,
        permission_mode="dontAsk",
        setting_sources=["project"],
        max_turns=MAX_TURNS,
        max_budget_usd=MAX_BUDGET_USD,
    )
    final: ResultMessage | None = None
    async for message in query(prompt=prompt_for(task), options=options):
        if isinstance(message, ResultMessage):
            final = message
    if final is None:
        return Result(ok=False, error="agent ended without a result")
    turns, cost = final.num_turns, final.total_cost_usd or 0.0
    if final.is_error:
        return Result(
            ok=False,
            error=f"agent stopped: {final.subtype}",
            turns=turns,
            cost_usd=cost,
        )
    return Result(ok=True, summary=final.result or "", turns=turns, cost_usd=cost)


def main(run_dir: Path) -> int:
    task = Task(**json.loads((run_dir / "task.json").read_text()))
    model = os.environ.get("DEV_AGENT_MODEL") or DEFAULT_MODEL
    print(
        f"dev agent starting on {task.issue_id} ({task.branch}) with {model}",
        flush=True,
    )
    try:
        result = asyncio.run(run_agent(run_dir, task))
        if result.ok and not commit_and_bundle(run_dir, task):
            result = Result(
                ok=False,
                error="agent made no changes",
                turns=result.turns,
                cost_usd=result.cost_usd,
            )
    except Exception as exc:  # noqa: BLE001 - always leave a result.json for the worker
        result = Result(ok=False, error=f"{type(exc).__name__}: {exc}")
    write_result(run_dir, result)
    print(
        f"dev agent finished ok={result.ok} turns={result.turns} cost=${result.cost_usd:.2f}"
        + (f" error={result.error}" if result.error else ""),
        flush=True,
    )
    return 0 if result.ok else 1


if __name__ == "__main__":
    sys.exit(main(Path(sys.argv[1])))
