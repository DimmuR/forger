"""Command template resolution and subprocess execution.

Security note: built-in runner commands use shell=False with shlex.split
to avoid shell injection.  Custom runner templates that use shell features
(pipes, env-var expansion) set shell=True — the trust boundary is the
config file, only the project owner writes runner templates.  Template
*variables* (model, prompt_arg, workdir, allowed_tools) are validated
here to block shell metacharacter injection from programmatic callers.
"""

__all__ = [
    "RunnerResult",
    "invoke_runner",
    "resolve_effort",
    "resolve_model",
    "resolve_runner",
    "resolve_tools",
]

import contextlib
import json
import os
import re
import shlex
import subprocess
import tempfile
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from forger.config import ProjectConfig, RunnerTemplate
from forger.events import EventEmitter

# Characters that are safe in template variable values.
# Blocks shell metacharacters: ; | & $ ` ( ) { } < > \ ! # ~ newline
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:/,=+ @-]+$")
_SHELL_METACHAR_RE = re.compile(r"[|;&`$<>(){}]")


@dataclass
class RunnerResult:
    exit_code: int
    duration_seconds: float
    timed_out: bool
    tokens: int = 0


def resolve_runner(config: ProjectConfig) -> RunnerTemplate:
    """Pick runner template from config."""
    return config.runners[config.default_runner]


def resolve_model(stage: str, config: ProjectConfig) -> str:
    """Pick model for a stage from config."""
    return config.models.stages.get(stage, config.models.default)


def resolve_tools(stage: str, config: ProjectConfig) -> list[str]:
    """Pick allowed tools list for a stage from config."""
    return config.tools.stages.get(stage, config.tools.default)


def resolve_effort(stage: str, config: ProjectConfig) -> str | None:
    """Pick effort level for a stage from config, or None for default."""
    return config.effort.stages.get(stage, config.effort.default)


def _tool_input_summary(tool_name: str, tool_input: dict[str, Any]) -> str:
    """Produce a short summary string for a tool_use event."""
    if tool_name in ("Read", "Write", "Edit"):
        path: str = tool_input.get("file_path", "")
        return path
    if tool_name == "Bash":
        cmd: str = tool_input.get("command", "")
        return cmd.split("\n")[0][:120]
    return tool_name


_ACTIVITY_COOLDOWN = 5  # seconds — suppress file-op lines within this window


class _ActivityTracker:
    """Collapse rapid file operations, always show Bash commands."""

    def __init__(self) -> None:
        self._pending_reads: list[str] = []
        self._pending_writes: list[str] = []
        self._last_print: float = 0

    def _flush_pending(self, elapsed: int) -> None:
        if self._pending_reads:
            n = len(self._pending_reads)
            if n <= 2:
                detail = ", ".join(self._pending_reads)
            else:
                detail = f"{self._pending_reads[0]} +{n - 1} more"
            print(f"  [{elapsed}s] Read {detail}", flush=True)
            self._pending_reads.clear()
        if self._pending_writes:
            detail = ", ".join(self._pending_writes)
            print(f"  [{elapsed}s] Write/Edit {detail}", flush=True)
            self._pending_writes.clear()

    def feed(self, tool_name: str, tool_input: dict, elapsed: int, now: float) -> None:
        if tool_name == "Read":
            path = tool_input.get("file_path", "")
            self._pending_reads.append(Path(path).name if path else "?")
            if now - self._last_print >= _ACTIVITY_COOLDOWN:
                self._flush_pending(elapsed)
                self._last_print = now
            return

        # Write/Edit — batch together
        if tool_name in ("Write", "Edit"):
            path = tool_input.get("file_path", "")
            name = Path(path).name if path else "?"
            tag = f"{tool_name} {name}"
            self._pending_writes.append(tag)
            if now - self._last_print >= _ACTIVITY_COOLDOWN:
                self._flush_pending(elapsed)
                self._last_print = now
            return

        # Bash — always print immediately (these are the slow/interesting ops)
        self._flush_pending(elapsed)
        if tool_name == "Bash":
            cmd = tool_input.get("command", "")
            short = cmd.split("\n")[0][:80]
            if short:
                print(f"  [{elapsed}s] Bash: {short}", flush=True)
                self._last_print = now
            return

        # Other tools — print name
        self._flush_pending(elapsed)
        print(f"  [{elapsed}s] {tool_name}", flush=True)
        self._last_print = now

    def flush(self, elapsed: int) -> None:
        self._flush_pending(elapsed)


def _parse_stream_line(line: str) -> dict[str, Any] | None:
    """Parse one stream-json line, return dict or None."""
    stripped = line.strip()
    if not stripped:
        return None
    try:
        data = json.loads(stripped)
        if isinstance(data, dict):
            return data  # type: ignore[no-any-return]
        return None
    except (json.JSONDecodeError, ValueError):
        return None


def invoke_runner(
    template: RunnerTemplate,
    prompt: str,
    workdir: Path,
    model: str,
    allowed_tools: list[str] | None = None,
    effort: str | None = None,
    timeout: int | None = None,
    log_file: Path | None = None,
    event_emitter: EventEmitter | None = None,
) -> RunnerResult:
    """Render command template, execute via subprocess, return result."""
    timeout = timeout or template.timeout

    # Write prompt to tempfile
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".md", prefix="forger-prompt-", delete=False
    ) as f:
        f.write(prompt)
        prompt_file = f.name

    try:
        tools_str = ",".join(allowed_tools) if allowed_tools else ""
        effort_str = f" --effort {effort}" if effort else ""
        # Validate all interpolated values to prevent shell injection.
        substitutions = {
            "model": model,
            "prompt_arg": prompt_file,
            "workdir": str(workdir),
            "allowed_tools": tools_str,
            "effort": effort_str,
        }
        for name, value in substitutions.items():
            if value and not _SAFE_VALUE_RE.match(value):
                raise ValueError(
                    f"Runner template variable '{name}' contains "
                    f"unsafe characters: {value!r}"
                )

        command = template.command.format(**substitutions)

        use_shell = bool(_SHELL_METACHAR_RE.search(command))

        env = os.environ.copy()
        for key, value in template.env.items():
            formatted = value.format(model=model)
            if formatted and not _SAFE_VALUE_RE.match(formatted):
                raise ValueError(
                    f"Runner env variable '{key}' contains "
                    f"unsafe characters after formatting: {formatted!r}"
                )
            env[key] = formatted

        start = time.monotonic()
        timed_out = False

        cmd = command if use_shell else shlex.split(command)
        proc = subprocess.Popen(
            cmd,
            shell=use_shell,
            cwd=workdir,
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Timeout watchdog: kills the process if deadline exceeded
        cancel_watchdog = threading.Event()
        killed_by_timeout = False

        def _watchdog():
            nonlocal killed_by_timeout
            deadline = timeout - (time.monotonic() - start)
            if deadline > 0 and not cancel_watchdog.wait(deadline):
                killed_by_timeout = True
                proc.kill()

        watchdog = threading.Thread(target=_watchdog, daemon=True)
        watchdog.start()

        # Stream stdout line-by-line, extracting progress from stream-json
        stdout_lines: list[str] = []
        last_heartbeat = start
        result_data: dict | None = None
        activity = _ActivityTracker()
        with contextlib.ExitStack() as stack:
            log_fh = stack.enter_context(open(log_file, "a")) if log_file else None
            try:
                for line in proc.stdout or []:
                    stdout_lines.append(line)
                    if log_fh:
                        log_fh.write(line)
                    now = time.monotonic()
                    elapsed = int(now - start)

                    event = _parse_stream_line(line)
                    if event:
                        etype = event.get("type")
                        if etype == "result":
                            result_data = event
                        elif etype == "assistant":
                            msg = event.get("message", {})
                            for block in msg.get("content", []):
                                if block.get("type") == "tool_use":
                                    tool_name = block.get("name", "")
                                    tool_input = block.get("input", {})
                                    activity.feed(
                                        tool_name,
                                        tool_input,
                                        elapsed,
                                        now,
                                    )
                                    if event_emitter:
                                        event_emitter.emit(
                                            "tool_use",
                                            name=tool_name,
                                            input_summary=_tool_input_summary(
                                                tool_name, tool_input
                                            ),
                                        )
                                    last_heartbeat = now

                    if now - last_heartbeat >= 30:
                        activity.flush(elapsed)
                        if event_emitter:
                            event_emitter.emit("heartbeat", elapsed_seconds=elapsed)
                        print(f"  [{elapsed}s] runner alive...", flush=True)
                        last_heartbeat = now

                activity.flush(int(time.monotonic() - start))
            finally:
                proc.wait()
                cancel_watchdog.set()
                watchdog.join(timeout=2)

        timed_out = killed_by_timeout
        stderr_output = proc.stderr.read() if proc.stderr else ""
        full_stdout = "".join(stdout_lines)

        if timed_out:
            exit_code = -1
            tokens = 0
        else:
            exit_code = proc.returncode

            # Extract token usage from stream-json result event
            tokens = 0
            log_content = full_stdout
            if result_data:
                usage = result_data.get("usage", {})
                tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
                log_content = result_data.get("result", full_stdout)
                if result_data.get("is_error"):
                    exit_code = exit_code or 1
            else:
                # Fallback: try legacy single-JSON parse
                try:
                    data = json.loads(full_stdout)
                    usage = data.get("usage", {})
                    tokens = usage.get("input_tokens", 0) + usage.get(
                        "output_tokens", 0
                    )
                    log_content = data.get("result", full_stdout)
                    if data.get("is_error"):
                        exit_code = exit_code or 1
                except (json.JSONDecodeError, TypeError, AttributeError):
                    log_content = full_stdout

        # Write summary to log (output lines already streamed above)
        if log_file:
            with open(log_file, "a") as lf:
                lf.write(f"\n{'=' * 60}\n")
                lf.write(f"Command: {command}\n")
                lf.write(f"Exit code: {exit_code}\n")
                lf.write(f"Tokens: {tokens}\n")
                lf.write(f"{'=' * 60}\n")
                if not stdout_lines and log_content:
                    lf.write(log_content)
                if stderr_output:
                    lf.write(f"\n--- stderr ---\n{stderr_output}")

        duration = time.monotonic() - start
        return RunnerResult(
            exit_code=exit_code,
            duration_seconds=duration,
            timed_out=timed_out,
            tokens=tokens,
        )
    finally:
        os.unlink(prompt_file)
