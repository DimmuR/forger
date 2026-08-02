"""Git and GitHub operations for forger push."""

__all__ = [
    "commit",
    "create_issue",
    "create_pr",
    "current_branch",
    "detect_repo",
    "gh_auth_info",
    "push",
    "repo_root",
    "switch_gh_account",
]

import re
import subprocess
from pathlib import Path

_SUBPROCESS_TIMEOUT = 120


def _run(
    cmd: list[str],
    cwd: Path | None = None,
    check: bool = True,
    timeout: int = _SUBPROCESS_TIMEOUT,
) -> subprocess.CompletedProcess[str]:
    """Run a command, raise RuntimeError on failure if check=True."""
    result = subprocess.run(
        cmd, capture_output=True, text=True, cwd=cwd, timeout=timeout
    )
    if check and result.returncode != 0:
        raise RuntimeError(
            f"{cmd[0]} failed: {result.stderr.strip()}"
            + (f"\nstdout: {result.stdout.strip()}" if result.stdout.strip() else "")
        )
    return result


def repo_root(cwd: Path | None = None) -> Path:
    """Find git repo root from a working directory."""
    result = _run(["git", "rev-parse", "--show-toplevel"], cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError("Not in a git repository")
    return Path(result.stdout.strip())


def gh_auth_info() -> list[str]:
    """Return filtered gh auth status lines (excluding token lines)."""
    result = _run(["gh", "auth", "status"], check=False)
    output = (result.stdout + result.stderr).strip()
    if not output:
        return []
    return [
        line.strip()
        for line in output.splitlines()
        if line.strip() and "Token:" not in line
    ]


def switch_gh_account(account: str, cwd: Path) -> None:
    """Switch gh CLI to a different GitHub account."""
    result = _run(["gh", "auth", "switch", "--user", account], cwd=cwd, check=False)
    if result.returncode != 0:
        raise RuntimeError(
            f"gh auth switch to '{account}' failed: {result.stderr.strip()}"
        )


def commit(message_file: Path, repo_dir: Path) -> str | None:
    """Create a commit with message from file. Returns commit SHA or None if nothing to commit."""
    # Stage only already-tracked files (modified/deleted) to avoid picking up
    # stray untracked files.  New files that the runner creates in the repo
    # should be explicitly added by the caller or the runner itself.
    result = _run(["git", "add", "-u"], cwd=repo_dir, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git add failed: {result.stderr}")

    # Check if there's anything staged
    result = _run(["git", "diff", "--cached", "--quiet"], cwd=repo_dir, check=False)
    if result.returncode == 0:
        return None  # Nothing to commit

    result = _run(["git", "commit", "-F", str(message_file)], cwd=repo_dir, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"git commit failed: {result.stderr}")

    result = _run(["git", "rev-parse", "--short", "HEAD"], cwd=repo_dir)
    return result.stdout.strip()


def push(branch: str, repo_dir: Path, branch_prefix: str = "forger") -> None:
    """Push branch to remote. Force-pushes only branches matching the configured prefix."""
    prefix = f"{branch_prefix}/"
    if not branch.startswith(prefix):
        raise ValueError(
            f"Refusing to force-push branch '{branch}': "
            f"does not start with '{prefix}'. "
            f"Forger only force-pushes its own branches."
        )
    _run(["git", "push", "--force", "-u", "origin", branch], cwd=repo_dir)


def create_issue(
    title: str,
    body_file: Path,
    cwd: Path | None = None,
    labels: list[str] | None = None,
) -> str:
    """Create GitHub issue via gh. Returns issue URL."""
    cmd = ["gh", "issue", "create", "--title", title, "--body-file", str(body_file)]
    repo = detect_repo(cwd)
    if repo:
        cmd.extend(["--repo", repo])
    if labels:
        cmd.extend(["--label", ",".join(labels)])
    result = _run(cmd, cwd=cwd)
    return result.stdout.strip()


def detect_repo(cwd: Path | None) -> str | None:
    """Detect owner/repo from git remote origin URL."""
    result = _run(["git", "remote", "get-url", "origin"], cwd=cwd, check=False)
    if result.returncode != 0:
        return None
    url = result.stdout.strip()
    m = re.search(r"github\.com[:/](.+?)(?:\.git)?$", url)
    return m.group(1) if m else None


def create_pr(
    title: str,
    body_file: Path,
    base: str = "main",
    draft: bool = True,
    cwd: Path | None = None,
    labels: list[str] | None = None,
) -> str:
    """Create GitHub PR via gh. Returns PR URL."""
    repo = detect_repo(cwd)
    cmd = [
        "gh",
        "pr",
        "create",
        "--title",
        title,
        "--body-file",
        str(body_file),
        "--base",
        base,
    ]
    if repo:
        cmd.extend(
            ["--repo", repo, "--head", f"{repo.split('/')[0]}:{current_branch(cwd)}"]
        )
    if draft:
        cmd.append("--draft")
    if labels:
        cmd.extend(["--label", ",".join(labels)])
    result = _run(cmd, cwd=cwd)
    return result.stdout.strip()


def current_branch(cwd: Path | None) -> str:
    result = _run(["git", "branch", "--show-current"], cwd=cwd, check=False)
    return result.stdout.strip()
