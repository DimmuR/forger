"""Create-patch stage: export working tree changes as a patch file. Harness-only (no LLM)."""

import subprocess
from pathlib import Path

from forger.config import ProjectConfig
from forger.git import repo_root
from forger.stages import check_stage_guards
from forger.state import save_change

CHANGE_FILE = "change.md"


def verify(run_dir: Path, config: ProjectConfig) -> bool:
    guards = check_stage_guards(run_dir, "drafted")
    if guards is None:
        return False
    state, body = guards
    change_path = run_dir / CHANGE_FILE

    work_dir = repo_root(run_dir)

    subprocess.run(["git", "add", "-A"], cwd=work_dir, check=True, capture_output=True)
    result = subprocess.run(
        ["git", "diff", "--cached", "HEAD"],
        cwd=work_dir,
        capture_output=True,
        text=True,
        check=True,
    )

    if not result.stdout.strip():
        state.pipeline.parked_reason = "create_patch: no changes to export"
        save_change(change_path, state, body)
        print("  ⛔ No changes to export as patch", flush=True)
        return False

    patch_file = run_dir / f"{state.id}.patch"
    patch_file.write_text(result.stdout)
    print(f"  Patch: {patch_file.name} ({len(result.stdout)} bytes)", flush=True)

    state.pipeline.stage = "patched"
    save_change(change_path, state, body)
    return True
