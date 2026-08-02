"""Tests for worktree helper functions (no git required)."""

import subprocess
from pathlib import Path

from forger.worktree import (
    _slugify,
    _worktree_path,
    create,
    path_for,
    recover_artifacts,
    relocate_run_dir,
    remove,
    worktree_run_dir,
)


def _init_repo(path: Path) -> str:
    """Create a git repo with one commit. Returns the default branch name."""
    subprocess.run(["git", "init", str(path)], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", str(path), "config", "user.email", "test@test.com"],
        capture_output=True,
        check=True,
    )
    subprocess.run(
        ["git", "-C", str(path), "config", "user.name", "Test"],
        capture_output=True,
        check=True,
    )
    (path / "README.md").write_text("# Test")
    subprocess.run(
        ["git", "-C", str(path), "add", "."], capture_output=True, check=True
    )
    subprocess.run(
        ["git", "-C", str(path), "commit", "-m", "init"],
        capture_output=True,
        check=True,
    )
    # Detect default branch name (master or main depending on git config)
    result = subprocess.run(
        ["git", "-C", str(path), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True,
        text=True,
        check=True,
    )
    return result.stdout.strip()


def test_slugify():
    assert _slugify("SENTRY-12345") == "sentry-12345"
    assert _slugify("foo/bar baz") == "foo--bar-baz"
    assert _slugify("PROJ-123") != _slugify("PROJ/123")


def test_worktree_path():
    repo = Path("/home/user/myproject")
    p = _worktree_path("issue-42", repo)
    assert p == Path("/home/user/myproject-wt-issue-42")


def test_worktree_run_dir():
    wt = Path("/tmp/proj-wt-abc")
    assert worktree_run_dir(wt) == wt / ".forger-run"


def test_relocate_run_dir(tmp_path):
    run_dir = tmp_path / "main" / ".forger" / "artifacts" / "sentry" / "run-123"
    run_dir.mkdir(parents=True)
    (run_dir / "change.md").write_text("---\nid: test\n---\nbody")
    (run_dir / "sentry-snapshot.json").write_text("{}")

    wt_path = tmp_path / "worktree"
    wt_path.mkdir()

    new_run_dir = relocate_run_dir(run_dir, wt_path)

    assert new_run_dir == wt_path / ".forger-run"
    assert (new_run_dir / "change.md").exists()
    assert (new_run_dir / "sentry-snapshot.json").exists()
    # Original still intact (copy, not move)
    assert (run_dir / "change.md").exists()


def test_relocate_idempotent(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "a.txt").write_text("original")

    wt_path = tmp_path / "wt"
    wt_path.mkdir()

    first = relocate_run_dir(run_dir, wt_path)
    (first / "b.txt").write_text("new file in worktree")

    # Second call doesn't overwrite
    second = relocate_run_dir(run_dir, wt_path)
    assert second == first
    assert (second / "b.txt").exists()


def test_recover_artifacts(tmp_path):
    wt_path = tmp_path / "wt"
    wt_run = wt_path / ".forger-run"
    wt_run.mkdir(parents=True)
    (wt_run / "change.md").write_text("updated content")
    (wt_run / "analysis.md").write_text("new artifact")
    reviews = wt_run / "reviews"
    reviews.mkdir()
    (reviews / "review-1.md").write_text("review content")

    canonical = tmp_path / "canonical"
    canonical.mkdir()
    (canonical / "change.md").write_text("old content")

    recover_artifacts(wt_path, canonical)

    assert (canonical / "change.md").read_text() == "updated content"
    assert (canonical / "analysis.md").read_text() == "new artifact"
    assert (canonical / "reviews" / "review-1.md").read_text() == "review content"


def test_recover_no_worktree_run_dir(tmp_path):
    wt_path = tmp_path / "wt"
    wt_path.mkdir()
    canonical = tmp_path / "canonical"
    canonical.mkdir()

    # Should not raise
    recover_artifacts(wt_path, canonical)


# --- Lifecycle tests (require real git repo) ---


def test_create_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    branch = _init_repo(repo)

    wt = create("test-run", repo, base_branch=branch, branch_prefix="forger")

    assert wt.exists()
    assert wt.is_dir()
    # Worktree should contain files from the repo
    assert (wt / "README.md").exists()
    assert (wt / "README.md").read_text() == "# Test"


def test_create_worktree_idempotent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    branch = _init_repo(repo)

    wt1 = create("idem-run", repo, base_branch=branch, branch_prefix="forger")
    wt2 = create("idem-run", repo, base_branch=branch, branch_prefix="forger")

    assert wt1 == wt2
    assert wt2.exists()


def test_remove_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    branch = _init_repo(repo)

    wt = create("rm-run", repo, base_branch=branch, branch_prefix="forger")
    assert wt.exists()

    remove("rm-run", repo, branch_prefix="forger")

    assert not wt.exists()
    # Branch should be deleted too
    result = subprocess.run(
        ["git", "-C", str(repo), "branch", "--list", "forger/rm-run"],
        capture_output=True,
        text=True,
    )
    assert result.stdout.strip() == ""


def test_remove_nonexistent_worktree(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    # Should not raise
    remove("no-such-run", repo, branch_prefix="forger")


def test_path_for_existing(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    branch = _init_repo(repo)

    wt = create("pf-run", repo, base_branch=branch, branch_prefix="forger")

    assert path_for("pf-run", repo) == wt


def test_path_for_nonexistent(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    _init_repo(repo)

    assert path_for("nonexistent", repo) is None
