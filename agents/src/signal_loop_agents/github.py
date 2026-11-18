import json
import urllib.request


def authed_remote_url(token: str, repo: str) -> str:
    return f"https://x-access-token:{token}@github.com/{repo}.git"


def create_pull_request(
    token: str, repo: str, *, head: str, base: str, title: str, body: str
) -> str:
    """Opens a pull request and returns its URL."""
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repo}/pulls",
        data=json.dumps(
            {"title": title, "head": head, "base": base, "body": body}
        ).encode(),
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "signal-loop-agent",
        },
    )
    with urllib.request.urlopen(request, timeout=30) as response:
        return json.load(response)["html_url"]
