"""Stage prompt assembly."""

__all__ = ["render_prompt"]

from pathlib import Path

from forger.config import ProjectConfig
from forger.stages import StageDef
from forger.state import ChangeState

SHARED_CONTRACT_PATH = Path(__file__).parent / "stages" / "run_contract.md"


def render_prompt(
    stage_def: StageDef,
    state: ChangeState,
    config: ProjectConfig,
    run_dir: Path,
    repo_dir: Path,
    project_dir: Path,
) -> str:
    """Assemble full prompt from stage definition + run context."""
    parts: list[str] = []

    # 1. Stage prompt
    if stage_def.prompt_path is not None:
        parts.append(stage_def.prompt_path.read_text())

    # 2. Stage-local references
    for ref in stage_def.references:
        parts.append(f"\n---\n## Reference: {ref.name}\n")
        parts.append(ref.read_text())

    # 3. Shared run contract
    if SHARED_CONTRACT_PATH.exists():
        parts.append("\n---\n## Run Contract\n")
        parts.append(SHARED_CONTRACT_PATH.read_text())

    # 4. Project guidelines
    guidelines_path = project_dir / ".forger" / "guidelines.md"
    if guidelines_path.exists():
        parts.append("\n---\n## Project Guidelines\n")
        parts.append(guidelines_path.read_text())

    # 5. Run context block
    parts.append(_build_context_block(state, config, run_dir, repo_dir))

    return "\n".join(parts)


def _build_context_block(
    state: ChangeState,
    config: ProjectConfig,
    run_dir: Path,
    repo_dir: Path,
) -> str:
    """Build the run context block appended to every prompt."""
    lines = [
        "\n---",
        "## Run Context",
        "",
        f"- Run ID: {state.id}",
        f"- Run directory: {run_dir}",
        f"- Repository root: {repo_dir}",
        f"- Current stage: {state.pipeline.stage}",
        f"- Source: {state.origin}",
    ]

    commands = config.resolve_commands(state.pipeline.stack)
    if commands:
        lines.append("")
        lines.append("### Project commands (use these, do not discover alternatives)")
        for name, cmd in commands.items():
            lines.append(f"- **{name}**: `{cmd}`")

    if state.evidence:
        lines.append("")
        lines.append("### Evidence from prior stages")
        for key, entry in state.evidence.items():
            exit_info = (
                f" (exit_code={entry.exit_code})" if entry.exit_code is not None else ""
            )
            summary = f" — {entry.summary}" if entry.summary else ""
            lines.append(f"- {key}{exit_info}{summary}")

    unresolved = {k: g for k, g in state.gates.items() if not g.resolved}
    if unresolved:
        lines.append("")
        lines.append("### Unresolved gates")
        for key, gate in unresolved.items():
            lines.append(f"- {key} (required={gate.required})")

    return "\n".join(lines)
