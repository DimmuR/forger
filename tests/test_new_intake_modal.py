"""Tests for the new intake modal screen."""

from __future__ import annotations

import asyncio
from pathlib import Path

from forger.tui.app import ForgerTUI
from forger.tui.intakes import IntakeConfig, IntakeParam
from forger.tui.screens.new_intake import IntakeRequest, NewIntakeModal


def _sentry_config() -> IntakeConfig:
    return IntakeConfig(
        source="sentry",
        label="Sentry Issue",
        params=[
            IntakeParam(
                key="issue_id",
                label="Issue ID",
                type="text",
                placeholder="PROJ-123",
                required=True,
            ),
        ],
    )


def _multi_source_configs() -> list[IntakeConfig]:
    return [
        _sentry_config(),
        IntakeConfig(
            source="github",
            label="GitHub Issue",
            params=[
                IntakeParam(
                    key="repo",
                    label="Repository",
                    type="text",
                    required=True,
                ),
                IntakeParam(
                    key="issue_number",
                    label="Issue #",
                    type="text",
                    required=True,
                ),
            ],
        ),
    ]


class TestNewIntakeModalRendering:
    def test_modal_has_source_select(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(NewIntakeModal([_sentry_config()]))
                await pilot.pause()
                assert app.screen.query_one("#source-select") is not None

        asyncio.run(_test())

    def test_modal_renders_params(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(NewIntakeModal([_sentry_config()]))
                await pilot.pause()
                assert app.screen.query_one("#param-issue_id") is not None

        asyncio.run(_test())

    def test_modal_has_buttons(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(NewIntakeModal([_sentry_config()]))
                await pilot.pause()
                assert app.screen.query_one("#btn-start") is not None
                assert app.screen.query_one("#btn-cancel") is not None

        asyncio.run(_test())


class TestNewIntakeModalValidation:
    def test_empty_required_blocks_submit(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(NewIntakeModal([_sentry_config()]))
                await pilot.pause()
                app.screen._submit()
                await pilot.pause()
                assert app.screen.__class__.__name__ == "NewIntakeModal"

        asyncio.run(_test())

    def test_valid_submit_dismisses(self):
        results: list[IntakeRequest | None] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:

                def capture(result: IntakeRequest | None) -> None:
                    results.append(result)

                app.push_screen(NewIntakeModal([_sentry_config()]), capture)
                await pilot.pause()
                app.screen.query_one("#param-issue_id").value = "TEST-42"
                app.screen._submit()
                await pilot.pause()
                assert app.screen.__class__.__name__ != "NewIntakeModal"

        asyncio.run(_test())
        assert len(results) == 1
        assert results[0] is not None
        assert results[0].source == "sentry"
        assert results[0].params == {"issue_id": "TEST-42"}


class TestNewIntakeModalDismiss:
    def test_escape_dismisses_with_none(self):
        results: list[IntakeRequest | None] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:

                def capture(result: IntakeRequest | None) -> None:
                    results.append(result)

                app.push_screen(NewIntakeModal([_sentry_config()]), capture)
                await pilot.pause()
                await pilot.press("escape")
                await pilot.pause()
                assert app.screen.__class__.__name__ != "NewIntakeModal"

        asyncio.run(_test())
        assert len(results) == 1
        assert results[0] is None

    def test_cancel_button_dismisses(self):
        results: list[IntakeRequest | None] = []

        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:

                def capture(result: IntakeRequest | None) -> None:
                    results.append(result)

                app.push_screen(NewIntakeModal([_sentry_config()]), capture)
                await pilot.pause()
                app.screen.query_one("#btn-cancel").press()
                await pilot.pause()

        asyncio.run(_test())
        assert len(results) == 1
        assert results[0] is None


class TestNewIntakeModalSourceSwitch:
    def test_switching_source_changes_params(self):
        async def _test():
            configs = _multi_source_configs()
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                app.push_screen(NewIntakeModal(configs))
                await pilot.pause()

                assert app.screen.query_one("#param-issue_id") is not None

                select = app.screen.query_one("#source-select")
                select.value = "github"
                await pilot.pause()

                assert app.screen.query_one("#param-repo") is not None
                assert app.screen.query_one("#param-issue_number") is not None
                assert len(app.screen.query("#param-issue_id")) == 0

        asyncio.run(_test())


class TestRunListIntegration:
    def test_n_opens_modal(self):
        async def _test():
            app = ForgerTUI(project_dir=Path("."))
            async with app.run_test(size=(80, 24)) as pilot:
                await pilot.press("n")
                await pilot.pause()
                assert app.screen.__class__.__name__ == "NewIntakeModal"

        asyncio.run(_test())

    def test_submit_returns_to_run_list(self, sentry_intake_dir):
        from unittest.mock import MagicMock, patch

        with patch(
            "forger.tui.spawner.subprocess.Popen", return_value=MagicMock(pid=1)
        ):

            async def _test():
                app = ForgerTUI(project_dir=sentry_intake_dir)
                async with app.run_test(size=(80, 24)) as pilot:
                    await pilot.press("n")
                    await pilot.pause()
                    app.screen.query_one("#param-issue_id").value = "TEST-99"
                    app.screen._submit()
                    await pilot.pause()
                    assert app.screen.__class__.__name__ == "RunListScreen"

            asyncio.run(_test())
