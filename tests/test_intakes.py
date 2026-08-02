"""Tests for intake discovery and config loading."""

from __future__ import annotations

from pathlib import Path

from forger.tui.intakes import IntakeParam, discover_intakes


def _write_intake_ui(stage_dir: Path, content: str) -> None:
    stage_dir.mkdir(parents=True, exist_ok=True)
    (stage_dir / "intake-ui.yml").write_text(content)


class TestIntakeParam:
    def test_defaults(self):
        p = IntakeParam(key="x", label="X")
        assert p.type == "text"
        assert p.placeholder == ""
        assert p.required is False
        assert p.options == []


class TestDiscoverIntakes:
    def test_discovers_package_sentry(self):
        intakes = discover_intakes()
        sources = [i.source for i in intakes]
        assert "sentry" in sources

    def test_sentry_config_shape(self):
        intakes = discover_intakes()
        sentry = next(i for i in intakes if i.source == "sentry")
        assert sentry.label == "Sentry Issue"
        assert len(sentry.params) == 1
        p = sentry.params[0]
        assert p.key == "issue_id"
        assert p.type == "text"
        assert p.required is True
        assert p.placeholder == "PROJ-123"

    def test_discovers_project_intake(self, tmp_path: Path):
        _write_intake_ui(
            tmp_path / ".forger" / "stages" / "github_intake",
            'label: "GitHub Issue"\n'
            "params:\n"
            "  - key: repo\n"
            '    label: "Repository"\n'
            "    type: text\n"
            "    required: true\n"
            "  - key: issue_number\n"
            '    label: "Issue #"\n'
            "    type: text\n"
            "    required: true\n",
        )
        intakes = discover_intakes(tmp_path)
        sources = {i.source for i in intakes}
        assert "github" in sources
        assert "sentry" in sources
        gh = next(i for i in intakes if i.source == "github")
        assert gh.label == "GitHub Issue"
        assert len(gh.params) == 2

    def test_project_overrides_package(self, tmp_path: Path):
        _write_intake_ui(
            tmp_path / ".forger" / "stages" / "sentry_intake",
            'label: "Custom Sentry"\n'
            "params:\n"
            "  - key: issue_id\n"
            '    label: "Custom ID"\n'
            "    type: text\n"
            "    required: true\n",
        )
        intakes = discover_intakes(tmp_path)
        sentry = next(i for i in intakes if i.source == "sentry")
        assert sentry.label == "Custom Sentry"
        assert sentry.params[0].label == "Custom ID"

    def test_no_project_stages_dir(self, tmp_path: Path):
        intakes = discover_intakes(tmp_path)
        assert len(intakes) >= 1

    def test_malformed_yaml_skipped(self, tmp_path: Path):
        stage_dir = tmp_path / ".forger" / "stages" / "bad_intake"
        stage_dir.mkdir(parents=True)
        (stage_dir / "intake-ui.yml").write_text("not: [valid: yaml: {{")
        intakes = discover_intakes(tmp_path)
        sources = {i.source for i in intakes}
        assert "bad" not in sources

    def test_empty_yaml_skipped(self, tmp_path: Path):
        stage_dir = tmp_path / ".forger" / "stages" / "empty_intake"
        stage_dir.mkdir(parents=True)
        (stage_dir / "intake-ui.yml").write_text("")
        intakes = discover_intakes(tmp_path)
        sources = {i.source for i in intakes}
        assert "empty" not in sources

    def test_no_intake_ui_yml_skipped(self, tmp_path: Path):
        stage_dir = tmp_path / ".forger" / "stages" / "noyml_intake"
        stage_dir.mkdir(parents=True)
        intakes = discover_intakes(tmp_path)
        sources = {i.source for i in intakes}
        assert "noyml" not in sources

    def test_select_param_type(self, tmp_path: Path):
        _write_intake_ui(
            tmp_path / ".forger" / "stages" / "custom_intake",
            'label: "Custom"\n'
            "params:\n"
            "  - key: priority\n"
            '    label: "Priority"\n'
            "    type: select\n"
            "    options: [high, medium, low]\n"
            "    required: false\n",
        )
        intakes = discover_intakes(tmp_path)
        custom = next(i for i in intakes if i.source == "custom")
        p = custom.params[0]
        assert p.type == "select"
        assert p.options == ["high", "medium", "low"]

    def test_bool_param_type(self, tmp_path: Path):
        _write_intake_ui(
            tmp_path / ".forger" / "stages" / "flag_intake",
            'label: "Flag"\n'
            "params:\n"
            "  - key: verbose\n"
            '    label: "Verbose"\n'
            "    type: bool\n",
        )
        intakes = discover_intakes(tmp_path)
        flag = next(i for i in intakes if i.source == "flag")
        assert flag.params[0].type == "bool"

    def test_label_fallback_to_source_title(self, tmp_path: Path):
        _write_intake_ui(
            tmp_path / ".forger" / "stages" / "nolabel_intake",
            'params:\n  - key: id\n    label: "ID"\n    type: text\n',
        )
        intakes = discover_intakes(tmp_path)
        nolabel = next(i for i in intakes if i.source == "nolabel")
        assert nolabel.label == "Nolabel"
