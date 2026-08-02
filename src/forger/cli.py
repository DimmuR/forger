"""Typer CLI for forger."""

from pathlib import Path

import typer

from forger import worktree
from forger.config import load_config
from forger.git import repo_root
from forger.orchestrator import (
    find_run_dir,
    reset_to_stage,
    run_pipeline,
)
from forger.pipeline import (
    STAGE_BY_NAME,
    STAGE_NAMES,
    next_stage,
)
from forger.prompt import render_prompt
from forger.stages import resolve_stage
from forger.state import load_change
from forger.summary import RunSummary, print_summary

__all__ = ["app"]

app = typer.Typer(no_args_is_help=True)


def _repo_dir() -> Path:
    """Find git repo root from cwd."""
    try:
        return repo_root()
    except RuntimeError as e:
        typer.echo("Error: not in a git repository.", err=True)
        raise typer.Exit(1) from e


@app.command(
    help="Run pipeline for an issue. Resumes if run already exists.",
    epilog="Examples:\n"
    "  forger run sentry PROJ-123\n"
    "  forger run sentry PROJ-123 --from implement\n"
    "  forger run sentry PROJ-123 --gate fix_choice=b\n"
    "  forger run sentry PROJ-123 --until review --skip prove",
)
def run(
    source: str,
    issue_id: str,
    gate: list[str] | None = typer.Option(None, help="Gate resolution: key=value"),
    from_stage: str | None = typer.Option(
        None, "--from", help="Reset to stage and rerun from there"
    ),
    until_stage: str | None = typer.Option(
        None, "--until", help="Stop after this stage completes"
    ),
    skip: str | None = typer.Option(None, help="Comma-separated stages to skip"),
):
    """Run pipeline for an issue. Resumes if run already exists."""
    repo_dir = _repo_dir()
    config = load_config(repo_dir)

    if from_stage:
        if from_stage not in STAGE_BY_NAME:
            typer.echo(
                f"Error: unknown stage '{from_stage}'. Valid: {', '.join(STAGE_NAMES)}",
                err=True,
            )
            raise typer.Exit(1)

        run_dir = find_run_dir(issue_id, repo_dir)
        if not run_dir:
            typer.echo(
                f"Error: run '{issue_id}' not found. Nothing to reset.", err=True
            )
            raise typer.Exit(1)

        wt_path = worktree.path_for(issue_id, repo_dir)
        if wt_path:
            active_run_dir = worktree.worktree_run_dir(wt_path)
            if active_run_dir.exists():
                run_dir = active_run_dir

        new_stage = reset_to_stage(run_dir, from_stage)
        typer.echo(f"Reset to '{new_stage}', rerunning from '{from_stage}'")

    gate_resolutions = {}
    if gate:
        for g in gate:
            key, _, value = g.partition("=")
            gate_resolutions[key] = value

    skip_stages = set(skip.split(",")) if skip else None
    outcome = run_pipeline(
        source=source,
        issue_id=issue_id,
        config=config,
        project_dir=repo_dir,
        repo_dir=repo_dir,
        gate_resolutions=gate_resolutions or None,
        until_stage=until_stage,
        skip_stages=skip_stages,
    )

    summary = (
        RunSummary.from_run(outcome.final_run_dir, outcome, source, issue_id)
        if outcome.final_run_dir
        else None
    )
    if summary:
        print_summary(summary)

    if outcome.blocked_reason:
        raise typer.Exit(1)


@app.command(
    help="Render current stage prompt to stdout (for debugging).",
    epilog="Examples:\n  forger prompt PROJ-123",
)
def prompt(run_id: str):
    """Render current stage prompt to stdout."""
    repo_dir = _repo_dir()
    config = load_config(repo_dir)

    run_dir = find_run_dir(run_id, repo_dir)
    if not run_dir:
        typer.echo(f"Error: run '{run_id}' not found.", err=True)
        raise typer.Exit(1)

    state, _body = load_change(run_dir / "change.md")

    stage_name = next_stage(state.pipeline.stage)
    if not stage_name:
        typer.echo(f"Error: no next stage for '{state.pipeline.stage}'.", err=True)
        raise typer.Exit(1)

    stage_def = resolve_stage(stage_name, state.origin, repo_dir)
    rendered = render_prompt(stage_def, state, config, run_dir, repo_dir, repo_dir)
    typer.echo(rendered)


@app.command(
    help="Show run status. No args: list all active runs.",
    epilog="Examples:\n  forger status\n  forger status PROJ-123",
)
def status(run_id: str | None = typer.Argument(None)):
    """Show run status. No args: list all active runs."""
    repo_dir = _repo_dir()
    artifacts_dir = repo_dir / ".forger" / "artifacts"

    if not artifacts_dir.exists():
        typer.echo("No runs found.")
        raise typer.Exit(0)

    if run_id:
        run_dir = find_run_dir(run_id, repo_dir)
        if not run_dir:
            typer.echo(f"Error: run '{run_id}' not found.", err=True)
            raise typer.Exit(1)
        state, _body = load_change(run_dir / "change.md")
        typer.echo(f"Run:      {state.id}")
        typer.echo(f"Title:    {state.title}")
        typer.echo(f"Source:   {state.origin}")
        typer.echo(f"Stage:    {state.pipeline.stage}")
        if state.pipeline.parked_reason:
            typer.echo(f"Parked:   {state.pipeline.parked_reason}")
        for gname, gval in state.gates.items():
            gate_status = f"resolved={gval.resolved}" if gval.resolved else "UNRESOLVED"
            typer.echo(f"Gate:     {gname} ({gate_status})")
    else:
        for source_dir in sorted(artifacts_dir.iterdir()):
            if not source_dir.is_dir():
                continue
            for run_dir in sorted(source_dir.iterdir()):
                if run_dir.name == "archive" or not run_dir.is_dir():
                    continue
                change_path = run_dir / "change.md"
                if not change_path.exists():
                    continue
                state, _ = load_change(change_path)
                typer.echo(
                    f"  {state.id:<40} {state.pipeline.stage:<15} {state.title[:50]}"
                )


@app.command(
    help="Create commit, push branch, issue, and PR from run deliverables.",
    epilog="Examples:\n  forger push PROJ-123",
)
def push(run_id: str):
    """Thin wrapper around the push stage's verify module."""
    from forger.stages import load_verify

    repo_dir = _repo_dir()
    config = load_config(repo_dir)

    run_dir = find_run_dir(run_id, repo_dir)
    if not run_dir:
        typer.echo(f"Error: run '{run_id}' not found.", err=True)
        raise typer.Exit(1)

    state, _ = load_change(run_dir / "change.md")
    source = state.origin

    stage_def = resolve_stage("push", source, repo_dir)
    verify_fn = load_verify(stage_def)
    if not verify_fn:
        typer.echo("Error: push stage has no verify module.", err=True)
        raise typer.Exit(1)

    success = verify_fn(run_dir, config)
    if success:
        typer.echo("Done.")
    else:
        typer.echo("Push failed or was parked. Check output above.", err=True)
        raise typer.Exit(1)


@app.command(
    help="Move completed run to archive.",
    epilog="Examples:\n  forger archive PROJ-123",
)
def archive(run_id: str):
    """Move completed run to archive."""
    repo_dir = _repo_dir()

    run_dir = find_run_dir(run_id, repo_dir)
    if not run_dir:
        typer.echo(f"Error: run '{run_id}' not found.", err=True)
        raise typer.Exit(1)

    source_dir = run_dir.parent
    archive_dir = source_dir / "archive"
    archive_dir.mkdir(exist_ok=True)

    dest = archive_dir / run_dir.name
    run_dir.rename(dest)
    typer.echo(f"Archived: {dest}")


@app.command(
    help="Initialize forger in current project.",
    epilog="Examples:\n  forger init",
)
def init():
    """Initialize forger in current project."""
    repo_dir = _repo_dir()
    forger_dir = repo_dir / ".forger"

    if forger_dir.exists():
        typer.echo(".forger/ already exists.")
        raise typer.Exit(0)

    forger_dir.mkdir()
    (forger_dir / "artifacts").mkdir()
    (forger_dir / "config.yaml").write_text(
        "# Forger project config\n"
        "# See: forger docs for available options\n"
        "commands:\n"
        '  test: "pytest"\n'
        '  lint: "ruff check ."\n'
    )

    exclude_path = repo_dir / ".git" / "info" / "exclude"
    if exclude_path.exists():
        content = exclude_path.read_text()
        if ".forger/" not in content:
            with open(exclude_path, "a") as f:
                f.write("\n.forger/\n")

    typer.echo(f"Initialized: {forger_dir}")
    typer.echo("Edit .forger/config.yaml to set test/lint commands.")
