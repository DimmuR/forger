"""Run summary data extraction and display."""

import re
from dataclasses import dataclass
from pathlib import Path

import typer

from forger.git import gh_auth_info
from forger.pipeline import STATE_LABEL, next_stage
from forger.state import TERMINAL_STAGES, RunOutcome, load_change

__all__ = ["EvidenceSummary", "GateSummary", "RunSummary", "print_summary"]


@dataclass
class EvidenceSummary:
    key: str
    exit_code: int | None
    summary: str | None


@dataclass
class GateSummary:
    key: str
    resolved: str | None
    rationale: str | None


@dataclass
class RunSummary:
    """Pure-data summary of a run, extracted from state for display or serialization."""

    title: str
    stage: str
    label: str
    body_heading: str | None
    body_lines: list[str]
    parked_reason: str | None
    blocked_reason: str | None
    evidence: list[EvidenceSummary]
    unresolved_gates: list[GateSummary]
    resolved_gates: list[GateSummary]
    fix_options: list[str]
    fix_recommendation: str | None
    artifacts: list[str]
    source: str
    issue_id: str
    github_pr: str | None

    @staticmethod
    def from_run(
        run_dir: Path, outcome: RunOutcome, source: str, issue_id: str
    ) -> "RunSummary | None":
        change_path = run_dir / "change.md"
        if not change_path.exists():
            return None

        state, body = load_change(change_path)
        stage = state.pipeline.stage
        label = STATE_LABEL.get(stage, stage)

        body_heading = None
        body_lines: list[str] = []
        if body.strip():
            sections = body.strip().split("\n## ")
            first_section = (
                sections[0].replace("## ", "", 1).strip() if sections else ""
            )
            for line in first_section.split("\n"):
                line = line.strip()
                if not line:
                    continue
                if line.startswith("#"):
                    body_heading = re.sub(r"^#+\s*", "", line).strip()
                else:
                    body_lines.append(line)

        parked_reason = state.pipeline.parked_reason
        blocked_reason = outcome.blocked_reason if not parked_reason else None

        evidence = [
            EvidenceSummary(
                key=key,
                exit_code=entry.exit_code,
                summary=entry.summary,
            )
            for key, entry in state.evidence.items()
        ]

        unresolved = [
            GateSummary(key=k, resolved=None, rationale=None)
            for k, v in state.gates.items()
            if not v.resolved
        ]
        resolved = [
            GateSummary(key=k, resolved=v.resolved, rationale=v.rationale)
            for k, v in state.gates.items()
            if v.resolved
        ]

        fix_options, fix_recommendation = _parse_fix_options(run_dir)

        artifacts = sorted(
            f.name
            for f in run_dir.iterdir()
            if f.name != "run.log" and not f.name.startswith(".")
        )

        return RunSummary(
            title=state.title,
            stage=stage,
            label=label,
            body_heading=body_heading,
            body_lines=body_lines,
            parked_reason=parked_reason,
            blocked_reason=blocked_reason,
            evidence=evidence,
            unresolved_gates=unresolved,
            resolved_gates=resolved,
            fix_options=fix_options,
            fix_recommendation=fix_recommendation,
            artifacts=artifacts,
            source=source,
            issue_id=issue_id,
            github_pr=state.github.pr,
        )


def _parse_fix_options(run_dir: Path) -> tuple[list[str], str | None]:
    """Parse fix-options.md for option headers and recommendation."""
    fix_opts = run_dir / "fix-options.md"
    if not fix_opts.exists():
        return [], None

    content = fix_opts.read_text()
    options = []
    for match in re.findall(r"^##\s+(.+)$", content, re.MULTILINE):
        opt = match.strip()
        if any(
            skip in opt.lower()
            for skip in ["recommendation", "summary", "context", "background"]
        ):
            continue
        options.append(opt)

    recommendation = None
    rec_match = re.search(
        r"(?:^##\s*Recommendation\s*\n)(.*?)(?=\n##|\Z)",
        content,
        re.MULTILINE | re.DOTALL,
    )
    if rec_match:
        rec_text = rec_match.group(1).strip().split("\n")[0].strip()
        if rec_text:
            recommendation = rec_text

    return options, recommendation


def _print_gh_auth():
    """Print current GitHub auth status."""
    lines = gh_auth_info()
    if lines:
        typer.echo("\n  GitHub auth:")
        for line in lines:
            typer.echo(f"    {line}")


def print_summary(summary: RunSummary):
    """Format and print a RunSummary."""
    typer.echo("")
    typer.echo(f"{'─' * 60}")
    typer.echo(f"  {summary.title}")
    typer.echo(f"  {summary.label}")
    typer.echo(f"{'─' * 60}")

    if summary.body_heading:
        typer.echo(f"\n  {summary.body_heading}:")
    for line in summary.body_lines[:5]:
        typer.echo(f"    {line}")
    if len(summary.body_lines) > 5:
        typer.echo(f"    ... (+{len(summary.body_lines) - 5} more lines)")

    if summary.parked_reason:
        typer.echo(f"\n  ⛔ {summary.parked_reason}")
        if (
            "push" in summary.parked_reason.lower()
            or "gh " in summary.parked_reason.lower()
        ):
            _print_gh_auth()
    elif summary.blocked_reason:
        typer.echo(f"\n  ⛔ {summary.blocked_reason}")

    if summary.evidence:
        typer.echo("\n  Evidence:")
        for ev in summary.evidence:
            status = f"exit={ev.exit_code}" if ev.exit_code is not None else "—"
            detail = f" — {ev.summary}" if ev.summary else ""
            typer.echo(f"    • {ev.key}: {status}{detail}")

    if summary.unresolved_gates:
        typer.echo("\n  Unresolved gates:")
        for g in summary.unresolved_gates:
            typer.echo(f"    • {g.key}")
        if (
            any(g.key == "fix_choice" for g in summary.unresolved_gates)
            and summary.fix_options
        ):
            typer.echo("\n  Fix options:")
            for opt in summary.fix_options:
                typer.echo(f"    • {opt}")
            if summary.fix_recommendation:
                typer.echo(f"  Recommendation: {summary.fix_recommendation}")

    if summary.resolved_gates:
        typer.echo("\n  Resolved gates:")
        for g in summary.resolved_gates:
            rationale = f" — {g.rationale}" if g.rationale else ""
            typer.echo(f"    • {g.key}: {g.resolved}{rationale}")

    typer.echo("\n  Next steps:")
    if summary.stage in TERMINAL_STAGES:
        if summary.stage == "pr-open":
            if summary.github_pr:
                typer.echo(f"    • Review PR: {summary.github_pr}")
            typer.echo(f"    • Archive: forger archive {summary.issue_id}")
        elif summary.stage == "parked":
            typer.echo("    • Investigate parked reason, then resume")
            typer.echo(f"    • Resume: forger run {summary.source} {summary.issue_id}")
    elif any(g.key == "fix_choice" for g in summary.unresolved_gates):
        typer.echo(
            f"    • Pick option: forger run {summary.source} {summary.issue_id} --gate fix_choice=<a|b|c>"
        )
    else:
        hint = next_stage(summary.stage)
        if hint:
            typer.echo(
                f"    • Continue: forger run {summary.source} {summary.issue_id}"
            )
            typer.echo(
                f"    • Resume from: forger run {summary.source} {summary.issue_id} --from {hint}"
            )
        else:
            typer.echo("    • Pipeline complete.")

    if summary.artifacts:
        typer.echo(f"\n  Artifacts: {', '.join(summary.artifacts)}")

    typer.echo(f"{'─' * 60}")
