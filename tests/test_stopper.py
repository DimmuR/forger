"""Tests for pipeline stop functionality."""

from __future__ import annotations

import asyncio
import json
import os
import signal
from pathlib import Path
from unittest.mock import patch

from forger.tui.app import ForgerTUI
from forger.tui.discovery import acquire_lock
from forger.tui.screens.confirm_archive import ConfirmModal
from forger.tui.stopper import (
    _emit_stopped_event,
    _send_signal,
    read_pid_from_lock,
    stop_pipeline,
)


class TestReadPidFromLock:
    def test_reads_pid(self, tmp_path):
        lock_dir = tmp_path / ".forger" / "locks"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / "run-PROJ-1.lock"
        lock_file.write_text("12345\n")
        assert read_pid_from_lock("PROJ-1", tmp_path) == 12345

    def test_returns_none_for_missing_file(self, tmp_path):
        assert read_pid_from_lock("PROJ-1", tmp_path) is None

    def test_returns_none_for_invalid_content(self, tmp_path):
        lock_dir = tmp_path / ".forger" / "locks"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / "run-PROJ-1.lock"
        lock_file.write_text("not-a-pid\n")
        assert read_pid_from_lock("PROJ-1", tmp_path) is None


class TestEmitStoppedEvent:
    def test_appends_event(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        _emit_stopped_event("PROJ-1", run_dir, tmp_path)
        events_file = run_dir / "events.jsonl"
        assert events_file.exists()
        event = json.loads(events_file.read_text().strip())
        assert event["type"] == "pipeline_stopped"
        assert event["reason"] == "user"
        assert "ts" in event

    def test_appends_to_existing(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        events_file = run_dir / "events.jsonl"
        events_file.write_text(
            '{"type":"pipeline_start","ts":"2024-01-01T00:00:00.000Z"}\n'
        )
        _emit_stopped_event("PROJ-1", run_dir, tmp_path)
        lines = events_file.read_text().strip().split("\n")
        assert len(lines) == 2
        assert json.loads(lines[1])["type"] == "pipeline_stopped"


class TestSendSignal:
    def test_killpg_success(self):
        with patch("forger.tui.stopper.os.killpg") as mock_killpg:
            assert _send_signal(123, signal.SIGTERM) is True
            mock_killpg.assert_called_once_with(123, signal.SIGTERM)

    def test_killpg_fails_falls_back_to_kill(self):
        with (
            patch("forger.tui.stopper.os.killpg", side_effect=PermissionError),
            patch("forger.tui.stopper.os.kill") as mock_kill,
        ):
            assert _send_signal(123, signal.SIGTERM) is True
            mock_kill.assert_called_once_with(123, signal.SIGTERM)

    def test_both_fail_returns_false(self):
        with (
            patch("forger.tui.stopper.os.killpg", side_effect=ProcessLookupError),
            patch("forger.tui.stopper.os.kill", side_effect=ProcessLookupError),
        ):
            assert _send_signal(123, signal.SIGTERM) is False


class TestStopPipeline:
    def test_returns_false_when_no_pid(self, tmp_path):
        run_dir = tmp_path / "run"
        run_dir.mkdir()
        assert stop_pipeline("PROJ-1", tmp_path, run_dir) is False

    def test_emits_event_before_signal(self, tmp_path):
        lock_dir = tmp_path / ".forger" / "locks"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / "run-PROJ-1.lock"
        lock_file.write_text("99999\n")

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        call_order = []

        def mock_send(pid, sig):
            events = (run_dir / "events.jsonl").read_text()
            call_order.append(
                (
                    "signal",
                    "event_exists" if "pipeline_stopped" in events else "no_event",
                )
            )
            return True

        with (
            patch("forger.tui.stopper._send_signal", side_effect=mock_send),
            patch("forger.tui.stopper.is_lock_held", return_value=False),
        ):
            stop_pipeline("PROJ-1", tmp_path, run_dir, timeout=0.5)

        assert call_order[0] == ("signal", "event_exists")

    def test_sigterm_then_sigkill_on_timeout(self, tmp_path):
        lock_dir = tmp_path / ".forger" / "locks"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / "run-PROJ-1.lock"
        lock_file.write_text("99999\n")

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        signals_sent = []

        def mock_send(pid, sig):
            signals_sent.append(sig)
            return True

        with (
            patch("forger.tui.stopper._send_signal", side_effect=mock_send),
            patch("forger.tui.stopper.is_lock_held", return_value=True),
        ):
            stop_pipeline("PROJ-1", tmp_path, run_dir, timeout=0.3, poll_interval=0.1)

        assert signals_sent[0] == signal.SIGTERM
        assert signals_sent[1] == signal.SIGKILL

    def test_returns_true_when_lock_releases(self, tmp_path):
        lock_dir = tmp_path / ".forger" / "locks"
        lock_dir.mkdir(parents=True)
        lock_file = lock_dir / "run-PROJ-1.lock"
        lock_file.write_text("99999\n")

        run_dir = tmp_path / "run"
        run_dir.mkdir()

        with (
            patch("forger.tui.stopper._send_signal", return_value=True),
            patch("forger.tui.stopper.is_lock_held", return_value=False),
        ):
            assert stop_pipeline("PROJ-1", tmp_path, run_dir) is True


def _make_stop_modal(issue_id: str) -> ConfirmModal:
    return ConfirmModal(
        "Stop Pipeline",
        f"Stop working on [b]{issue_id}[/b]?",
        variant="error",
        error_border=True,
    )


class TestConfirmStopModal:
    def test_modal_renders_issue_id(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(_make_stop_modal("PROJ-123"))
                await pilot.pause()
                body = app.screen.query_one("#confirm-body")
                assert "PROJ-123" in str(body.render())

        asyncio.run(_test())

    def test_yes_button_dismisses_true(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(_make_stop_modal("X-1"), results.append)
                await pilot.pause()
                app.screen.query_one("#btn-yes").press()
                await pilot.pause()

        asyncio.run(_test())
        assert results == [True]

    def test_no_button_dismisses_false(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(_make_stop_modal("X-1"), results.append)
                await pilot.pause()
                app.screen.query_one("#btn-no").press()
                await pilot.pause()

        asyncio.run(_test())
        assert results == [False]

    def test_escape_dismisses_false(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(_make_stop_modal("X-1"), results.append)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()

        asyncio.run(_test())
        assert results == [False]

    def test_y_key_confirms(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(_make_stop_modal("X-1"), results.append)
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

        asyncio.run(_test())
        assert results == [True]


class TestStopFromRunList:
    def _make_running_run(self, tmp_path: Path, issue_id: str = "TEST-1"):
        """Create a run that appears as RUNNING (lock held)."""
        source_dir = tmp_path / ".forger" / "artifacts" / "sentry"
        run_dir = source_dir / f"run-{issue_id}"
        run_dir.mkdir(parents=True)
        change = run_dir / "change.md"
        change.write_text(
            f"---\nid: {issue_id}\ntitle: test\norigin: sentry\n"
            f"pipeline:\n  stage: analyze\n  parked_reason: null\n---\n"
        )
        fd = acquire_lock(issue_id, tmp_path)
        return run_dir, fd

    def test_s_on_non_running_shows_warning(self, tmp_path):
        source_dir = tmp_path / ".forger" / "artifacts" / "sentry"
        run_dir = source_dir / "run-TEST-1"
        run_dir.mkdir(parents=True)
        change = run_dir / "change.md"
        change.write_text(
            "---\nid: TEST-1\ntitle: test\norigin: sentry\n"
            "pipeline:\n  stage: pr-open\n  parked_reason: null\n---\n"
        )

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "RunListScreen"

        asyncio.run(_test())

    def test_s_on_empty_list_does_nothing(self, tmp_path):
        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("s")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "RunListScreen"

        asyncio.run(_test())

    def test_s_on_running_opens_confirm(self, tmp_path):
        _run_dir, fd = self._make_running_run(tmp_path)
        try:

            async def _test():
                app = ForgerTUI(project_dir=tmp_path)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.pause()
                    await pilot.press("s")
                    await pilot.pause()
                    assert isinstance(app.screen, ConfirmModal)

            asyncio.run(_test())
        finally:
            os.close(fd)
