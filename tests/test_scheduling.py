"""Tests for TUI scheduling: deferred runs with file-backed timers."""

from __future__ import annotations

import asyncio
import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock, patch

from forger.tui.app import ForgerTUI
from forger.tui.discovery import RunStatus, discover_runs
from forger.tui.screens.new_intake import _parse_schedule
from forger.tui.spawner import cancel_schedule, schedule_pipeline


def _make_scheduled_run(
    tmp_path: Path,
    issue_id: str = "TEST-1",
    *,
    source: str = "sentry",
    fire_at: datetime | None = None,
    cancelled: bool = False,
    started: bool = False,
) -> Path:
    """Create a run dir with pipeline_scheduled event."""
    if fire_at is None:
        fire_at = datetime.now(UTC) + timedelta(hours=1)
    run_dir = tmp_path / ".forger" / "artifacts" / source / f"run-{issue_id}"
    run_dir.mkdir(parents=True, exist_ok=True)
    lines = [
        json.dumps(
            {
                "ts": "2026-08-03T10:00:00.000Z",
                "type": "pipeline_scheduled",
                "fire_at": fire_at.isoformat(),
                "source": source,
                "issue_id": issue_id,
                "params": {"issue_id": issue_id},
            }
        )
    ]
    if cancelled:
        lines.append(
            json.dumps(
                {
                    "ts": "2026-08-03T10:01:00.000Z",
                    "type": "pipeline_schedule_cancelled",
                    "reason": "user",
                }
            )
        )
    if started:
        lines.append(
            json.dumps(
                {
                    "ts": "2026-08-03T12:00:00.000Z",
                    "type": "pipeline_start",
                    "source": source,
                    "issue_id": issue_id,
                }
            )
        )
    (run_dir / "events.jsonl").write_text("\n".join(lines) + "\n")
    return run_dir


class TestSchedulePipeline:
    def test_creates_run_dir(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        run_dir = schedule_pipeline("sentry", "PROJ-1", tmp_path, fire_at)
        assert run_dir.exists()
        assert (run_dir / "events.jsonl").exists()

    def test_writes_pipeline_scheduled_event(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        run_dir = schedule_pipeline(
            "sentry", "PROJ-1", tmp_path, fire_at, {"issue_id": "PROJ-1"}
        )
        events = (run_dir / "events.jsonl").read_text().strip().split("\n")
        assert len(events) == 1
        ev = json.loads(events[0])
        assert ev["type"] == "pipeline_scheduled"
        assert ev["fire_at"] == fire_at.isoformat()
        assert ev["source"] == "sentry"
        assert ev["issue_id"] == "PROJ-1"
        assert ev["params"] == {"issue_id": "PROJ-1"}

    def test_returns_run_dir_path(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        run_dir = schedule_pipeline("sentry", "PROJ-1", tmp_path, fire_at)
        assert run_dir == tmp_path / ".forger" / "artifacts" / "sentry" / "run-PROJ-1"


class TestCancelSchedule:
    def test_writes_pipeline_schedule_cancelled_event(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        run_dir = schedule_pipeline("sentry", "PROJ-1", tmp_path, fire_at)
        cancel_schedule(run_dir)
        events = (run_dir / "events.jsonl").read_text().strip().split("\n")
        assert len(events) == 2
        ev = json.loads(events[1])
        assert ev["type"] == "pipeline_schedule_cancelled"
        assert ev["reason"] == "user"


class TestParseSchedule:
    def test_time_only_future_today(self):
        now = datetime.now()
        future_hour = (now.hour + 2) % 24
        result = _parse_schedule(f"{future_hour:02d}:00")
        assert result is not None
        local = result.astimezone()
        assert local.hour == future_hour
        assert local.minute == 0

    def test_time_only_past_wraps_to_tomorrow(self):
        now = datetime.now()
        past_hour = (now.hour - 2) % 24
        result = _parse_schedule(f"{past_hour:02d}:{now.minute:02d}")
        assert result is not None
        local = result.astimezone()
        assert local.date() > now.date() or (
            local.date() == now.date() and local.hour > now.hour
        )

    def test_full_datetime_future(self):
        future = datetime.now() + timedelta(days=1)
        raw = future.strftime("%Y-%m-%d %H:%M")
        result = _parse_schedule(raw)
        assert result is not None

    def test_full_datetime_past_returns_none(self):
        past = datetime.now() - timedelta(days=1)
        raw = past.strftime("%Y-%m-%d %H:%M")
        result = _parse_schedule(raw)
        assert result is None

    def test_invalid_format_returns_none(self):
        assert _parse_schedule("not-a-time") is None
        assert _parse_schedule("25:00") is None
        assert _parse_schedule("") is None


class TestScheduledStatusDetection:
    def test_scheduled_future(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        _make_scheduled_run(tmp_path, "PROJ-1", fire_at=fire_at)
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.SCHEDULED
        assert runs[0].fire_at is not None

    def test_missed_past(self, tmp_path: Path):
        fire_at = datetime.now(UTC) - timedelta(hours=1)
        _make_scheduled_run(tmp_path, "PROJ-1", fire_at=fire_at)
        runs = discover_runs(tmp_path)
        assert len(runs) == 1
        assert runs[0].status == RunStatus.MISSED

    def test_cancelled_not_shown(self, tmp_path: Path):
        _make_scheduled_run(tmp_path, "PROJ-1", cancelled=True)
        runs = discover_runs(tmp_path)
        assert len(runs) == 0

    def test_started_not_scheduled(self, tmp_path: Path):
        """Once pipeline_start fires, run is no longer SCHEDULED."""
        _make_scheduled_run(tmp_path, "PROJ-1", started=True)
        runs = discover_runs(tmp_path)
        # No change.md → only visible if lock held, so 0 runs
        assert len(runs) == 0

    def test_scheduled_stage_label(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        _make_scheduled_run(tmp_path, "PROJ-1", fire_at=fire_at)
        runs = discover_runs(tmp_path)
        assert runs[0].stage == "scheduled"

    def test_scheduled_title_is_issue_id(self, tmp_path: Path):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        _make_scheduled_run(tmp_path, "PROJ-1", fire_at=fire_at)
        runs = discover_runs(tmp_path)
        assert runs[0].title == "PROJ-1"

    def test_multiple_scheduled_and_regular(self, tmp_path: Path):
        from forger.state import ChangeState, PipelineState, save_change

        fire_at = datetime.now(UTC) + timedelta(hours=1)
        _make_scheduled_run(tmp_path, "SCHED-1", fire_at=fire_at)
        # Regular completed run
        run_dir = tmp_path / ".forger" / "artifacts" / "sentry" / "run-REG-1"
        run_dir.mkdir(parents=True)
        state = ChangeState(
            id="sentry-REG-1",
            title="Regular run",
            origin="sentry",
            pipeline=PipelineState(stage="pr-open"),
        )
        save_change(run_dir / "change.md", state, "body")
        runs = discover_runs(tmp_path)
        assert len(runs) == 2
        statuses = {r.issue_id: r.status for r in runs}
        assert statuses["SCHED-1"] == RunStatus.SCHEDULED
        assert statuses["REG-1"] == RunStatus.COMPLETED


class TestScheduleIntegration:
    def test_schedule_from_modal(self, sentry_intake_dir):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        fire_str = fire_at.astimezone().strftime("%Y-%m-%d %H:%M")

        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=123)

            async def _test():
                app = ForgerTUI(project_dir=sentry_intake_dir)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one("#param-issue_id").value = "TEST-42"
                    app.screen.query_one("#schedule-input").value = fire_str
                    app.screen._submit()
                    await pilot.pause()

            asyncio.run(_test())

        # Should NOT have called Popen (scheduled, not immediate)
        mock_popen.assert_not_called()
        # Should have created run dir with events
        run_dir = sentry_intake_dir / ".forger" / "artifacts" / "sentry" / "run-TEST-42"
        assert run_dir.exists()
        events = (run_dir / "events.jsonl").read_text().strip().split("\n")
        ev = json.loads(events[0])
        assert ev["type"] == "pipeline_scheduled"

    def test_immediate_spawn_no_schedule(self, sentry_intake_dir):
        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=123)

            async def _test():
                app = ForgerTUI(project_dir=sentry_intake_dir)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one("#param-issue_id").value = "TEST-43"
                    # schedule-input left empty → immediate spawn
                    app.screen._submit()
                    await pilot.pause()

            asyncio.run(_test())

        mock_popen.assert_called_once()

    def test_cancel_scheduled_run(self, sentry_intake_dir):
        fire_at = datetime.now(UTC) + timedelta(hours=1)
        _make_scheduled_run(sentry_intake_dir, "TEST-44", fire_at=fire_at)

        async def _test():
            app = ForgerTUI(project_dir=sentry_intake_dir)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                # Find the scheduled run row and select it
                await pilot.press("c")
                await pilot.pause()
                # Confirm the cancel
                from forger.tui.screens.confirm_archive import ConfirmModal

                modal = app.screen
                if isinstance(modal, ConfirmModal):
                    modal.action_confirm()
                await pilot.pause()

        asyncio.run(_test())

        run_dir = sentry_intake_dir / ".forger" / "artifacts" / "sentry" / "run-TEST-44"
        events_text = (run_dir / "events.jsonl").read_text()
        assert "pipeline_schedule_cancelled" in events_text

    def test_duplicate_issue_id_blocked(self, sentry_intake_dir):
        from tests.factories import make_tui_run

        make_tui_run(sentry_intake_dir, "DUPE-1", stage="triaged")

        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=123)

            async def _test():
                app = ForgerTUI(project_dir=sentry_intake_dir)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one("#param-issue_id").value = "DUPE-1"
                    app.screen._submit()
                    await pilot.pause()

            asyncio.run(_test())

        mock_popen.assert_not_called()
