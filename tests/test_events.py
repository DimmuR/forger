"""Tests for EventEmitter and events.jsonl integration."""

import json
import stat
import sys
from pathlib import Path

import pytest

from forger.config import BUILTIN_DEFAULTS, ProjectConfig, RunnerTemplate
from forger.events import EventEmitter
from forger.orchestrator import ensure_run_dir, run_pipeline
from forger.state import ChangeState, PipelineState, save_change


class TestEventEmitter:
    """Unit tests for the EventEmitter class."""

    def test_emit_writes_jsonl(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        emitter.emit("test_event", foo="bar", count=42)
        emitter.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 1
        event = json.loads(lines[0])
        assert event["type"] == "test_event"
        assert event["foo"] == "bar"
        assert event["count"] == 42
        assert "ts" in event

    def test_emit_multiple_events(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        emitter.emit("first", x=1)
        emitter.emit("second", x=2)
        emitter.emit("third", x=3)
        emitter.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 3
        types = [json.loads(line)["type"] for line in lines]
        assert types == ["first", "second", "third"]

    def test_emit_ts_format(self, tmp_path):
        emitter = EventEmitter(tmp_path)
        emitter.emit("test")
        emitter.close()

        event = json.loads(
            (tmp_path / "events.jsonl").read_text().strip().splitlines()[0]
        )
        ts = event["ts"]
        # ISO 8601 with milliseconds and Z suffix
        assert ts.endswith("Z")
        assert "T" in ts
        assert "." in ts

    def test_reattach(self, tmp_path):
        dir_a = tmp_path / "a"
        dir_b = tmp_path / "b"
        dir_a.mkdir()
        dir_b.mkdir()

        emitter = EventEmitter(dir_a)
        emitter.emit("before_reattach")
        emitter.reattach(dir_b)
        emitter.emit("after_reattach")
        emitter.close()

        events_a = (dir_a / "events.jsonl").read_text().strip().splitlines()
        events_b = (dir_b / "events.jsonl").read_text().strip().splitlines()
        assert len(events_a) == 1
        assert json.loads(events_a[0])["type"] == "before_reattach"
        assert len(events_b) == 1
        assert json.loads(events_b[0])["type"] == "after_reattach"

    def test_append_mode(self, tmp_path):
        """EventEmitter appends to existing file."""
        (tmp_path / "events.jsonl").write_text(
            json.dumps({"ts": "old", "type": "existing"}) + "\n"
        )
        emitter = EventEmitter(tmp_path)
        emitter.emit("new_event")
        emitter.close()

        lines = (tmp_path / "events.jsonl").read_text().strip().splitlines()
        assert len(lines) == 2
        assert json.loads(lines[0])["type"] == "existing"
        assert json.loads(lines[1])["type"] == "new_event"


_PYTHON = sys.executable


class TestOrchestratorEvents:
    """Integration tests: events emitted during pipeline runs."""

    @pytest.fixture
    def config(self):
        cfg = ProjectConfig.model_validate(BUILTIN_DEFAULTS)
        cfg.runners["claude"] = RunnerTemplate(command="bash {prompt_arg}", timeout=30)
        cfg.commands = {"test": "echo test", "lint": "echo lint"}
        cfg.worktree = False
        return cfg

    @pytest.fixture
    def project_dir(self, tmp_path):
        forger_dir = tmp_path / ".forger"
        forger_dir.mkdir()
        (forger_dir / "artifacts" / "sentry").mkdir(parents=True)
        return tmp_path

    def _load_events(self, run_dir: Path) -> list[dict]:
        path = run_dir / "events.jsonl"
        if not path.exists():
            return []
        return [json.loads(line) for line in path.read_text().strip().splitlines()]

    def test_single_stage_emits_pipeline_and_stage_events(
        self, project_dir, config, tmp_path
    ):
        run_dir = ensure_run_dir("sentry", "EVT-001", project_dir)

        state = ChangeState(
            id="sentry-EVT-001",
            title="Test bug",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="triaged"),
        )
        save_change(run_dir / "change.md", state, "Test.")

        script = f"""#!/bin/bash
cat > {run_dir}/analysis.md << 'EOF'
# Root Cause
Found it.
EOF
"""
        script_path = run_dir / "runner.sh"
        script_path.write_text(script)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        config.runners["claude"] = RunnerTemplate(
            command=f"bash {script_path}", timeout=30
        )

        run_pipeline(
            source="sentry",
            issue_id="EVT-001",
            config=config,
            project_dir=project_dir,
            repo_dir=project_dir,
        )

        events = self._load_events(run_dir)
        types = [e["type"] for e in events]
        assert "pipeline_start" in types
        assert "pipeline_end" in types
        assert "stage_start" in types
        assert "stage_end" in types

        # pipeline_start has correct fields
        ps = next(e for e in events if e["type"] == "pipeline_start")
        assert ps["source"] == "sentry"
        assert ps["issue_id"] == "EVT-001"

        # stage_start/end for analyze
        ss = next(e for e in events if e["type"] == "stage_start")
        assert ss["name"] == "analyze"

        se = next(e for e in events if e["type"] == "stage_end")
        assert se["name"] == "analyze"
        assert se["success"] is True
        assert se["error"] is None
        assert "elapsed_seconds" in se

        # pipeline_end
        pe = next(e for e in events if e["type"] == "pipeline_end")
        assert "total_tokens" in pe
        assert "total_elapsed_seconds" in pe

    def test_parked_pipeline_emits_blocked(self, project_dir, config):
        run_dir = ensure_run_dir("sentry", "EVT-002", project_dir)

        state = ChangeState(
            id="sentry-EVT-002",
            title="Parked bug",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(
                stage="analyzed",
                parked_reason="Need Redis",
            ),
        )
        save_change(run_dir / "change.md", state, "Test.")

        run_pipeline(
            source="sentry",
            issue_id="EVT-002",
            config=config,
            project_dir=project_dir,
            repo_dir=project_dir,
        )

        events = self._load_events(run_dir)
        blocked = [e for e in events if e["type"] == "blocked"]
        assert len(blocked) >= 1
        assert "Need Redis" in blocked[0]["reason"]

    def test_skip_stage_emits_skip_event(self, project_dir, config, tmp_path):
        run_dir = ensure_run_dir("sentry", "EVT-003", project_dir)

        state = ChangeState(
            id="sentry-EVT-003",
            title="Skip test",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="triaged"),
        )
        save_change(run_dir / "change.md", state, "Test.")

        # Pipeline will try analyze, which we skip.
        # It will then try prove, which will fail (no runner script).
        # But we should see the skip event for analyze.
        run_pipeline(
            source="sentry",
            issue_id="EVT-003",
            config=config,
            project_dir=project_dir,
            repo_dir=project_dir,
            skip_stages={"analyze"},
        )

        events = self._load_events(run_dir)
        skip_events = [e for e in events if e["type"] == "skip"]
        assert len(skip_events) == 1
        assert skip_events[0]["name"] == "analyze"

    def test_failed_stage_emits_stage_end_with_error(self, project_dir, config):
        run_dir = ensure_run_dir("sentry", "EVT-004", project_dir)

        state = ChangeState(
            id="sentry-EVT-004",
            title="Fail test",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="triaged"),
        )
        save_change(run_dir / "change.md", state, "Test.")

        # Runner that exits non-zero
        config.runners["claude"] = RunnerTemplate(command="false", timeout=30)

        run_pipeline(
            source="sentry",
            issue_id="EVT-004",
            config=config,
            project_dir=project_dir,
            repo_dir=project_dir,
        )

        events = self._load_events(run_dir)
        stage_ends = [e for e in events if e["type"] == "stage_end"]
        assert len(stage_ends) == 1
        assert stage_ends[0]["success"] is False
        assert stage_ends[0]["error"] is not None

    def test_gate_blocks_emits_blocked_with_gate(self, project_dir, config):
        run_dir = ensure_run_dir("sentry", "EVT-005", project_dir)

        state = ChangeState(
            id="sentry-EVT-005",
            title="Gate test",
            origin="sentry",
            created="2026-07-18",
            updated="2026-07-18",
            pipeline=PipelineState(stage="proven"),
        )
        save_change(run_dir / "change.md", state, "Test.")

        src_path = Path(__file__).parent.parent / "src"
        script = (
            f"#!/bin/bash\n"
            f"cat > {run_dir}/fix-options.md << 'FIXEOF'\n"
            f"# Options\n"
            f"a: fast fix\n"
            f"FIXEOF\n"
            f'PYTHONPATH="{src_path}" {_PYTHON} -c "\n'
            f"from forger.state import load_change, save_change, Gate\n"
            f"from pathlib import Path\n"
            f"state, body = load_change(Path('{run_dir}/change.md'))\n"
            f"state.gates['fix_choice'] = Gate(required=True, resolved=None)\n"
            f"save_change(Path('{run_dir}/change.md'), state, body)\n"
            f'"\n'
        )
        script_path = run_dir / "runner.sh"
        script_path.write_text(script)
        script_path.chmod(script_path.stat().st_mode | stat.S_IEXEC)
        config.runners["claude"] = RunnerTemplate(
            command=f"bash {script_path}", timeout=30
        )

        run_pipeline(
            source="sentry",
            issue_id="EVT-005",
            config=config,
            project_dir=project_dir,
            repo_dir=project_dir,
        )

        events = self._load_events(run_dir)
        blocked = [e for e in events if e["type"] == "blocked"]
        assert len(blocked) >= 1
        assert blocked[0]["gate"] == "fix_choice"


class TestRunnerToolUseEvents:
    """Test that invoke_runner emits tool_use events from stream-json."""

    def test_tool_use_emitted_from_stream_json(self, tmp_path):
        """Simulate stream-json output containing tool_use blocks."""
        from forger.runner import invoke_runner

        emitter = EventEmitter(tmp_path)

        # Build a script that outputs stream-json with a tool_use block
        tool_use_event = json.dumps(
            {
                "type": "assistant",
                "message": {
                    "content": [
                        {
                            "type": "tool_use",
                            "name": "Read",
                            "input": {"file_path": "/src/foo.py"},
                        }
                    ]
                },
            }
        )
        script = tmp_path / "stream.sh"
        script.write_text(f"#!/bin/bash\necho '{tool_use_event}'\n")
        script.chmod(script.stat().st_mode | stat.S_IEXEC)

        template = RunnerTemplate(command=f"bash {script}", timeout=10)
        invoke_runner(
            template,
            "test prompt",
            tmp_path,
            "sonnet",
            timeout=10,
            event_emitter=emitter,
        )
        emitter.close()

        events_path = tmp_path / "events.jsonl"
        events = [
            json.loads(line) for line in events_path.read_text().strip().splitlines()
        ]
        tool_events = [e for e in events if e["type"] == "tool_use"]
        assert len(tool_events) == 1
        assert tool_events[0]["name"] == "Read"
        assert tool_events[0]["input_summary"] == "/src/foo.py"

    def test_no_events_without_emitter(self, tmp_path):
        """No events.jsonl when event_emitter is None."""
        from forger.runner import invoke_runner

        template = RunnerTemplate(command="echo done", timeout=10)
        invoke_runner(template, "test prompt", tmp_path, "sonnet", timeout=10)

        assert not (tmp_path / "events.jsonl").exists()


class TestToolInputSummary:
    """Unit tests for _tool_input_summary."""

    def test_read_file_path(self):
        from forger.runner import _tool_input_summary

        assert _tool_input_summary("Read", {"file_path": "/a/b/c.py"}) == "/a/b/c.py"

    def test_write_file_path(self):
        from forger.runner import _tool_input_summary

        assert _tool_input_summary("Write", {"file_path": "/x.txt"}) == "/x.txt"

    def test_edit_file_path(self):
        from forger.runner import _tool_input_summary

        assert (
            _tool_input_summary("Edit", {"file_path": "/src/mod.py"}) == "/src/mod.py"
        )

    def test_bash_command_snippet(self):
        from forger.runner import _tool_input_summary

        result = _tool_input_summary("Bash", {"command": "ls -la\necho done"})
        assert result == "ls -la"

    def test_bash_long_command_truncated(self):
        from forger.runner import _tool_input_summary

        long_cmd = "x" * 200
        result = _tool_input_summary("Bash", {"command": long_cmd})
        assert len(result) == 120

    def test_other_tool_returns_name(self):
        from forger.runner import _tool_input_summary

        assert _tool_input_summary("WebSearch", {"query": "test"}) == "WebSearch"
