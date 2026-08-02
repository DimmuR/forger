# Contributing to Forger

## Prerequisites

- Python 3.12+
- [uv](https://docs.astral.sh/uv/) for dependency management

## Setup

```bash
git clone https://github.com/DimmuR/forger.git
cd forger
uv sync
```

This installs all dependencies including dev tools (pytest, mypy). `uv.lock` is committed for reproducible builds — always use `uv sync` for development, not `pip install`.

## Running tests

```bash
uv run pytest
```

## Type checking

```bash
uv run pyright
uv run mypy src/
```

## Linting & formatting

```bash
uv run ruff check
uv run ruff format --check
```

## Project structure

```
src/forger/
  cli.py            # Typer CLI (run, status, prompt, push, archive, init)
  orchestrator.py   # Pipeline loop
  pipeline.py       # Stage definitions and sequencing
  config.py         # Config loading and merging
  state.py          # Change state model (change.md frontmatter)
  runner.py         # Command template resolution and subprocess execution
  prompt.py         # Stage prompt assembly with run context
  summary.py        # Run summary extraction and display
  git.py            # Git and GitHub operations (commit, push, PR)
  worktree.py       # Git worktree lifecycle management
  stages/           # Built-in pipeline stages
```

## Adding a new stage

Each stage lives in `src/forger/stages/<name>/` with a `prompt.md`. Simple stages declare their verify checks in `pipeline.py` via `VerifyCheck` (required files, evidence checks, gate checks). Stages with complex verify logic (review loopback, push orchestration) use a `verify.py` file instead.

See [docs/extending.md](docs/extending.md) for the full guide.

## Adding a new source

Sources follow the `<source>_intake` stage convention. To add a `github` source:

1. Create `src/forger/stages/github_intake/` with `prompt.md` and `verify.py`
2. The intake stage produces a `change.md` with valid `ChangeState` frontmatter
3. Register a `StageSpec` in `pipeline.py`

The stage resolution system supports source-specific overrides: `github_analyze`
takes priority over `analyze` for the `github` source.

See [docs/extending.md](docs/extending.md) for details.

## Code style

The project uses standard Python conventions:
- Type hints where practical
- Pydantic models for data structures
- Docstrings for public APIs

## Submitting changes

1. Fork the repository
2. Create a feature branch
3. Make your changes with tests
4. Run `uv run pytest`, `uv run pyright`, and `uv run ruff check`
5. Open a pull request against `master`

## Releasing

1. Update version in `pyproject.toml` and `src/forger/__init__.py`
2. Update `CHANGELOG.md` — move `Unreleased` to dated version header
3. Commit: `release: v0.x.y`
4. Tag: `git tag v0.x.y`
5. Build: `uv build`
6. Push: `git push && git push --tags`
