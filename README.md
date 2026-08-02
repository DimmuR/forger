# Forger

[![CI](https://github.com/DimmuR/forger/actions/workflows/ci.yml/badge.svg)](https://github.com/DimmuR/forger/actions/workflows/ci.yml)
[![License](https://img.shields.io/badge/License-Apache_2.0-blue.svg)](https://opensource.org/licenses/Apache-2.0)

Forger is an AI-powered bug-fixing pipeline orchestrator. It takes bugs from sources like Sentry, runs them through a multi-stage pipeline (intake, analyze, prove, fix_options, implement, review, draft, push), where each stage invokes an LLM runner (Claude Code, Goose, or any CLI tool) with a structured prompt, then a Python verification module checks the results before advancing. The key insight: **verification modules own stage transitions, not the LLM.** The harness decides what happens next based on file-system evidence, making the pipeline reliable regardless of which model or runner executes the work.

> **v0.1.0 -- Experimental.** This is early software. Expect breaking changes to configuration, CLI interface, and stage contracts.

## Install

```bash
# Install from source
pip install git+https://github.com/DimmuR/forger.git

# Or clone and install locally
git clone https://github.com/DimmuR/forger.git
cd forger
pip install .
```

Requires Python 3.12+.

## Quick start

```bash
# Initialize forger in your project
forger init

# Configure your runner and test/lint commands in .forger/config.yaml
# Then run against a Sentry issue
forger run sentry PROJ-123
```

Forger creates a `.forger/` directory in your project root containing configuration, artifacts, and run state. `forger init` adds `.forger/` to `.git/info/exclude` (local-only, not committed) so it stays out of version control without modifying `.gitignore`. Contributors who fork should run `forger init` to set this up.

## Pipeline stages

Each run flows through these stages. Intake is source-specific; everything after is source-agnostic.

```
sentry_intake  →  Fetch issue data, create change.md, declare flow
analyze        →  Identify root cause, affected files, tech stack
prove          →  Write a failing test that reproduces the bug
fix_options    →  Propose 2-3 fix strategies with tradeoffs
implement      →  Apply the chosen fix, make the proof test pass
review         →  Multi-reviewer code review (quality + challenge roles)
draft          →  Write commit message, PR description, changelog entry
push           →  Commit, push branch, create GitHub issue and PR
```

Stages produce artifacts (analysis.md, proof.md, fix-options.md, reviews/) that subsequent stages consume. Verification modules check post-conditions after each stage and decide whether to advance, loop back (review can retry implement), or park the run.

## CLI commands

| Command | Description |
|---|---|
| `forger run <source> <issue-id>` | Run pipeline for an issue. Resumes if a run already exists. |
| `forger prompt <run-id>` | Render current stage prompt to stdout (for debugging). |
| `forger status [run-id]` | Show run status, or list all active runs. |
| `forger push <run-id>` | Manually trigger commit/push/PR creation. |
| `forger archive <run-id>` | Move completed run to archive. |
| `forger init` | Initialize `.forger/` in current project. |

### Run options

```bash
# Resume from a specific stage
forger run sentry PROJ-123 --from implement

# Stop after a specific stage
forger run sentry PROJ-123 --until review

# Skip stages
forger run sentry PROJ-123 --skip prove,review

# Resolve a gate (e.g., pick fix option)
forger run sentry PROJ-123 --gate fix_choice=a
```

## Configuration

Config loads with precedence: **built-in defaults < global (`~/.forger/config.yaml`) < project (`.forger/config.yaml`)**.

Key settings: runner command templates, model selection per stage, tool allowlists, test/lint commands, multi-reviewer setup, worktree isolation.

See [docs/configuration.md](docs/configuration.md) for the full reference.

## Architecture

- **Source-agnostic core.** Only intake stages know about the bug source (Sentry, manual, etc.). Everything else reads normalized artifacts.
- **Command-template runners.** Runners are YAML config, not Python classes. Adding a runner = adding a config entry.
- **Verify owns transitions.** Each stage's `verify.py` decides what happens next -- advance, loop back, or park. The orchestration loop is deliberately simple.
- **Git worktree isolation.** Each run gets its own worktree for parallel execution without conflicts.

## Extending

Forger is designed for extensibility:
- **New sources**: write an intake stage that produces `change.md`
- **New runners**: add a command template to config
- **Custom stages**: add prompt + verify to `.forger/stages/`
- **Project guidelines**: add `.forger/guidelines.md` to inject rules into every prompt

See [docs/extending.md](docs/extending.md) for details.

## License

[Apache-2.0](LICENSE)
