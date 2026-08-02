"""Tests for the confirm archive modal and archive action."""

from __future__ import annotations

import asyncio
from pathlib import Path

from forger.tui.app import ForgerTUI
from forger.tui.screens.confirm_archive import ConfirmArchiveModal


class TestConfirmArchiveModal:
    def test_modal_renders_issue_id(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(ConfirmArchiveModal("PROJ-123"))
                await pilot.pause()
                title = app.screen.query_one("#confirm-title")
                assert title is not None
                body = app.screen.query_one("#confirm-body")
                assert "PROJ-123" in str(body.render())

        asyncio.run(_test())

    def test_yes_button_dismisses_true(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(ConfirmArchiveModal("X-1"), results.append)
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
                app.push_screen(ConfirmArchiveModal("X-1"), results.append)
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
                app.push_screen(ConfirmArchiveModal("X-1"), results.append)
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
                app.push_screen(ConfirmArchiveModal("X-1"), results.append)
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

        asyncio.run(_test())
        assert results == [True]

    def test_n_key_cancels(self):
        results: list[bool] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(ConfirmArchiveModal("X-1"), results.append)
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()

        asyncio.run(_test())
        assert results == [False]


class TestArchiveFromRunList:
    def _make_run_dir(self, tmp_path: Path, issue_id: str = "TEST-1"):
        """Create minimal run structure for archive testing."""
        source_dir = tmp_path / ".forger" / "artifacts" / "sentry"
        run_dir = source_dir / issue_id
        run_dir.mkdir(parents=True)
        change = run_dir / "change.md"
        change.write_text(
            f"---\nid: {issue_id}\ntitle: test\norigin: sentry\n"
            f"pipeline:\n  stage: pr-open\n  parked_reason: null\n---\n"
        )
        return run_dir, source_dir

    def test_d_opens_confirm_on_non_running(self, tmp_path):
        _run_dir, _ = self._make_run_dir(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "ConfirmArchiveModal"

        asyncio.run(_test())

    def test_confirm_yes_archives_run(self, tmp_path):
        run_dir, source_dir = self._make_run_dir(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                await pilot.press("y")
                await pilot.pause()

        asyncio.run(_test())
        assert not run_dir.exists()
        assert (source_dir / "archive" / "TEST-1").exists()

    def test_confirm_no_keeps_run(self, tmp_path):
        run_dir, _ = self._make_run_dir(tmp_path)

        async def _test():
            app = ForgerTUI(project_dir=tmp_path)
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                await pilot.press("n")
                await pilot.pause()

        asyncio.run(_test())
        assert run_dir.exists()

    def test_d_on_empty_list_does_nothing(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.pause()
                await pilot.press("d")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "RunListScreen"

        asyncio.run(_test())
