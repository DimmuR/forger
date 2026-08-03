"""Tests for pipeline restart functionality."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from forger.tui.app import ForgerTUI
from forger.tui.screens.confirm_archive import ConfirmModal
from tests.factories import (
    make_completed_run,
    make_crashed_run,
    make_failed_run,
    make_stopped_run,
)


class TestRestartFromRunList:
    def test_r_on_stopped_opens_confirm(self, tmp_path):
        make_stopped_run(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmModal)

        asyncio.run(_test())

    def test_r_on_crashed_opens_confirm(self, tmp_path):
        make_crashed_run(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmModal)

        asyncio.run(_test())

    def test_r_on_failed_opens_confirm(self, tmp_path):
        make_failed_run(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmModal)

        asyncio.run(_test())

    def test_r_on_completed_shows_warning(self, tmp_path):
        make_completed_run(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "RunListScreen"

        asyncio.run(_test())

    def test_r_on_empty_list_does_nothing(self, tmp_path):
        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "RunListScreen"

        asyncio.run(_test())

    def test_confirm_yes_calls_spawn(self, tmp_path):
        make_stopped_run(tmp_path)
        spawn_calls = []

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                assert isinstance(app.screen, ConfirmModal)
                with patch(
                    "forger.tui.screens.run_list.spawn_pipeline",
                    side_effect=lambda *a: spawn_calls.append(a),
                ):
                    await pilot.press("y")
                    await pilot.pause()
                    await pilot.pause()

        asyncio.run(_test())
        assert len(spawn_calls) == 1
        source, issue_id, _project_dir = spawn_calls[0]
        assert source == "sentry"
        assert issue_id == "TEST-1"

    def test_confirm_no_does_not_spawn(self, tmp_path):
        make_stopped_run(tmp_path)
        spawn_calls = []

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("r")
                await pilot.pause()
                with patch(
                    "forger.tui.screens.run_list.spawn_pipeline",
                    side_effect=lambda *a: spawn_calls.append(a),
                ):
                    await pilot.press("n")
                    await pilot.pause()

        asyncio.run(_test())
        assert len(spawn_calls) == 0
