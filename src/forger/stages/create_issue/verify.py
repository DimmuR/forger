"""Create-issue stage: create GitHub issue from issue.md. Harness-only (no LLM)."""

from pathlib import Path

from forger.config import ProjectConfig
from forger.git import create_issue, repo_root
from forger.stages import check_stage_guards
from forger.state import save_change

CHANGE_FILE = "change.md"
ISSUE_FILE = "issue.md"


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "pushed")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / CHANGE_FILE

    if state.github.issue:
        state.pipeline.stage = "issue-created"
        save_change(change_path, state, body)
        return True

    issue_file = run_dir / ISSUE_FILE
    if not issue_file.exists():
        state.pipeline.parked_reason = f"create_issue: {ISSUE_FILE} not found"
        save_change(change_path, state, body)
        print(f"  ⛔ {ISSUE_FILE} not found", flush=True)
        return False

    work_dir = repo_root(run_dir)

    try:
        content = issue_file.read_text()
        lines = content.splitlines()
        title = lines[0].lstrip("# ").strip() if lines else "Untitled"
        url = create_issue(title, issue_file, cwd=work_dir)
        print(f"  Issue: {url}", flush=True)
        state.github.issue = url
    except RuntimeError as e:
        state.pipeline.parked_reason = f"create_issue: {e}"
        save_change(change_path, state, body)
        print(f"  ⛔ Issue creation failed: {e}", flush=True)
        return False

    state.pipeline.stage = "issue-created"
    save_change(change_path, state, body)
    return True
