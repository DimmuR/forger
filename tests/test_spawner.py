"""Tests for TUI subprocess spawning."""

from __future__ import annotations

import asyncio
import subprocess
from unittest.mock import MagicMock, patch

from forger.tui.app import ForgerTUI
from forger.tui.spawner import spawn_pipeline


class TestSpawnPipeline:
    def test_creates_run_dir(self, tmp_path):
        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            spawn_pipeline("sentry", "PROJ-1", tmp_path)

        run_dir = tmp_path / ".forger" / "artifacts" / "sentry" / "run-PROJ-1"
        assert run_dir.exists()

    def test_creates_stdout_log(self, tmp_path):
        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            spawn_pipeline("sentry", "PROJ-1", tmp_path)

        log = (
            tmp_path / ".forger" / "artifacts" / "sentry" / "run-PROJ-1" / "stdout.log"
        )
        assert log.exists()

    def test_popen_called_with_correct_args(self, tmp_path):
        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=12345)
            spawn_pipeline("sentry", "PROJ-1", tmp_path)

        args = mock_popen.call_args
        cmd = args[0][0]
        assert cmd[-3:] == ["run", "sentry", "PROJ-1"]
        assert args[1]["cwd"] == str(tmp_path)
        assert args[1]["start_new_session"] is True
        assert args[1]["stderr"] == subprocess.STDOUT

    def test_returns_popen_handle(self, tmp_path):
        sentinel = MagicMock(pid=99)
        with patch("forger.tui.spawner.subprocess.Popen", return_value=sentinel):
            result = spawn_pipeline("sentry", "PROJ-1", tmp_path)
        assert result is sentinel


class TestRunListSpawnIntegration:
    def test_submit_spawns_subprocess(self, sentry_intake_dir):
        with patch("forger.tui.spawner.subprocess.Popen") as mock_popen:
            mock_popen.return_value = MagicMock(pid=123)

            async def _test():
                app = ForgerTUI(project_dir=sentry_intake_dir)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one("#param-issue_id").value = "TEST-42"
                    app.screen._submit()
                    await pilot.pause()

            asyncio.run(_test())

        mock_popen.assert_called_once()
        cmd = mock_popen.call_args[0][0]
        assert "sentry" in cmd
        assert "TEST-42" in cmd

    def test_submit_empty_issue_id_shows_error(self, sentry_intake_dir):
        async def _test():
            app = ForgerTUI(project_dir=sentry_intake_dir)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.press("n")
                await pilot.pause()
                app.screen.query_one("#param-issue_id").value = ""
                app.screen._submit()
                await pilot.pause()
                assert app.screen.__class__.__name__ == "NewIntakeModal"

        asyncio.run(_test())
