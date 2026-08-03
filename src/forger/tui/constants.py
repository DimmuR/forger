"""Shared constants and formatters for TUI components."""

from __future__ import annotations

from datetime import UTC, datetime

from forger.tui.discovery import RunStatus

STAGE_SHORT: dict[str, str] = {
    "sentry_intake": "intake",
    "analyze": "analyze",
    "prove": "prove",
    "fix_options": "fix_opts",
    "implement": "impl",
    "review": "review",
    "draft": "draft",
    "push": "push",
}

STATUS_STYLES: dict[RunStatus, str] = {
    RunStatus.RUNNING: "bold cyan",
    RunStatus.STOPPING: "bold dark_orange",
    RunStatus.COMPLETED: "bold green",
    RunStatus.STOPPED: "dim",
    RunStatus.FAILED: "bold red",
    RunStatus.CRASHED: "bold red reverse",
    RunStatus.BLOCKED: "bold yellow",
    RunStatus.NEEDS_ATTENTION: "bold dark_orange",
    RunStatus.SCHEDULED: "bold blue",
    RunStatus.MISSED: "bold dark_orange reverse",
}


def format_elapsed(started: datetime | None, ended: datetime | None) -> str:
    """Format elapsed time as H:MM:SS or M:SS."""
    if started is None:
        return "—"
    end = ended or datetime.now(UTC)
    total_secs = int((end - started).total_seconds())
    if total_secs < 0:
        return "—"
    hours, remainder = divmod(total_secs, 3600)
    mins, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{mins:02d}:{secs:02d}"
    return f"{mins}:{secs:02d}"


def format_seconds(s: int) -> str:
    """Format raw seconds as H:MM:SS, M:SS, or Ns."""
    if s >= 3600:
        return f"{s // 3600}:{(s % 3600) // 60:02d}:{s % 60:02d}"
    if s >= 60:
        return f"{s // 60}:{s % 60:02d}"
    return f"{s}s"


def format_started(started: datetime | None) -> str:
    """Format start time as local HH:MM or date+time if not today."""
    if started is None:
        return "—"
    local = started.astimezone()
    today = datetime.now().date()
    if local.date() == today:
        return local.strftime("%H:%M")
    return local.strftime("%m-%d %H:%M")


def format_tokens(count: int) -> str:
    """Format token count as compact string (e.g. 12.3k)."""
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def format_fire_at(fire_at: datetime | None) -> str:
    """Format scheduled fire time as local HH:MM or date+time if not today."""
    if fire_at is None:
        return "—"
    local = fire_at.astimezone()
    today = datetime.now().date()
    if local.date() == today:
        return f"@ {local.strftime('%H:%M')}"
    return f"@ {local.strftime('%m-%d %H:%M')}"


def stage_label(stage: str) -> str:
    """Map pipeline state string to short display name."""
    from forger.pipeline import STAGES

    for spec in STAGES:
        if spec.post_state == stage or spec.pre_state == stage:
            return STAGE_SHORT.get(spec.name, spec.name)
    return stage
