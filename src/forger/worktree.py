"""Git worktree lifecycle management."""

__all__ = [
    "create",
    "path_for",
    "recover_artifacts",
    "relocate_run_dir",
    "remove",
    "worktree_run_dir",
]

import shutil
import subprocess
import warnings
from pathlib import Path


def _slugify(run_id: str) -> str:
    """Convert run_id to a filesystem-safe slug.

    Uses per-character replacement to avoid collisions where distinct IDs
    (e.g. PROJ-123 vs PROJ/123) would otherwise map to the same slug.
    """
    result = []
    for ch in run_id.lower():
        if ch in "abcdefghijklmnopqrstuvwxyz0123456789_-":
            result.append(ch)
        elif ch == "/":
            result.append("--")
        elif ch == " ":
            result.append("-")
        else:
            result.append(f"-{ord(ch):x}-")
    return "".join(result).strip("-")


def _worktree_path(run_id: str, repo_dir: Path) -> Path:
    """Compute worktree path as sibling to repo."""
    slug = _slugify(run_id)
    repo_name = repo_dir.name
    return repo_dir.parent / f"{repo_name}-wt-{slug}"


def create(
    run_id: str,
    repo_dir: Path,
    base_branch: str,
    branch_prefix: str,
) -> Path:
    """Create worktree for a run. Returns worktree path. Idempotent."""
    wt_path = _worktree_path(run_id, repo_dir)
    if wt_path.exists():
        return wt_path

    branch_name = f"{branch_prefix}/{_slugify(run_id)}"

    result = subprocess.run(
        ["git", "worktree", "add", "-b", branch_name, str(wt_path), base_branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        # Branch might already exist
        result = subprocess.run(
            ["git", "worktree", "add", str(wt_path), branch_name],
            cwd=repo_dir,
            capture_output=True,
            text=True,
        )
        if result.returncode != 0:
            raise RuntimeError(f"git worktree add failed: {result.stderr}")

    return wt_path


def path_for(run_id: str, repo_dir: Path) -> Path | None:
    """Resolve existing worktree path. Returns None if not found."""
    wt_path = _worktree_path(run_id, repo_dir)
    if wt_path.exists():
        return wt_path
    return None


RUN_DIR_NAME = ".forger-run"


def worktree_run_dir(wt_path: Path) -> Path:
    """Canonical run_dir location inside a worktree."""
    return wt_path / RUN_DIR_NAME


def relocate_run_dir(run_dir: Path, wt_path: Path) -> Path:
    """Copy run_dir into the worktree. Returns new run_dir path."""
    dest = worktree_run_dir(wt_path)
    if dest.exists():
        return dest
    shutil.copytree(run_dir, dest)
    (dest / ".gitignore").write_text("*\n")
    return dest


def recover_artifacts(wt_path: Path, run_dir: Path) -> None:
    """Copy artifacts back from worktree to canonical run_dir in main tree."""
    src = worktree_run_dir(wt_path)
    if not src.exists():
        return
    for item in src.iterdir():
        dest_item = run_dir / item.name
        if item.is_dir():
            if dest_item.exists():
                shutil.rmtree(dest_item)
            shutil.copytree(item, dest_item)
        else:
            shutil.copy2(item, dest_item)


def remove(run_id: str, repo_dir: Path, branch_prefix: str = "forger") -> None:
    """Remove worktree and delete its branch."""
    wt_path = _worktree_path(run_id, repo_dir)
    if not wt_path.exists():
        return

    result = subprocess.run(
        ["git", "worktree", "remove", "--force", str(wt_path)],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        warnings.warn(
            f"Failed to remove worktree {wt_path}: {result.stderr.strip()}",
            stacklevel=2,
        )

    slug = _slugify(run_id)
    branch = f"{branch_prefix}/{slug}"
    result = subprocess.run(
        ["git", "branch", "-d", branch],
        cwd=repo_dir,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        warnings.warn(
            f"Failed to delete branch {branch}: {result.stderr.strip()}",
            stacklevel=2,
        )
