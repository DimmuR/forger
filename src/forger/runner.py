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

from forger.config import ProjectConfig, RunnerTemplate

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


def invoke_runner(
    template: RunnerTemplate,
    prompt: str,
    workdir: Path,
    model: str,
    allowed_tools: list[str] | None = None,
    timeout: int | None = None,
    log_file: Path | None = None,
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
        # Validate all interpolated values to prevent shell injection.
        substitutions = {
            "model": model,
            "prompt_arg": prompt_file,
            "workdir": str(workdir),
            "allowed_tools": tools_str,
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

        # Stream stdout line-by-line
        stdout_lines: list[str] = []
        last_heartbeat = start
        with contextlib.ExitStack() as stack:
            log_fh = stack.enter_context(open(log_file, "a")) if log_file else None
            try:
                for line in proc.stdout or []:
                    stdout_lines.append(line)
                    if log_fh:
                        log_fh.write(line)
                    now = time.monotonic()
                    if now - last_heartbeat >= 30:
                        elapsed = int(now - start)
                        print(f"  [{elapsed}s] runner alive...", flush=True)
                        last_heartbeat = now
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

            # Parse JSON output for token usage
            tokens = 0
            log_content = full_stdout
            try:
                data = json.loads(full_stdout)
                usage = data.get("usage", {})
                tokens = usage.get("input_tokens", 0) + usage.get("output_tokens", 0)
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
