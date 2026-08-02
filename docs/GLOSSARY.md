# FORGER Domain Glossary

## Core concepts

- **Run** — a single end-to-end pipeline execution for one issue/bug. Identified by a run ID (e.g., `run-ACME-APP-16K`). Has a working directory under `<project>/.forger/artifacts/<source>/<run-id>/`.

- **Stage** — one step in a pipeline run. Each stage has a prompt and optional verification logic. A stage receives the run's working directory, reads/writes files, and advances the run's state. Examples: `analyze`, `prove`, `implement`.

- **Pipeline topology** — the ordered sequence of stages every run follows, defined as a static `STAGES` tuple in `pipeline.py`. All runs share the same stage order; per-run variation is handled via `--skip`, `--from`, and `--until` CLI flags, not per-run flow lists.

- **Source** — the origin system of a bug/issue (e.g., `sentry`, `manual`). Each source has one or more intake stages. Everything after intake is source-agnostic.

- **Intake** — a source-specific stage that creates `change.md`. The only part of the pipeline that knows about the source system.

- **Runner** — an external CLI tool that executes a stage prompt in a working directory (e.g., Claude Code CLI, goose). Configured as command templates. FORGER invokes runners via subprocess.

- **Gate** — a decision point that may pause the pipeline ("which way?"). Has a key, possible resolutions, and optional rationale. Can auto-resolve (e.g., quick-wins skip fix choice) or require human input. Example: `fix_choice` gate after `fix-options` stage.

- **Parked** — a run that cannot proceed due to an external blocker ("can't move at all"). No in-pipeline resolution exists — the blocker is outside the pipeline's control. Examples: "needs-instance" (frontend testing), max retries exceeded. Resume by fixing the external condition and clearing `parked_reason`.

- **Evidence** — machine-verifiable proof collected during a run. Stored in `change.md` frontmatter. Examples: proof test exit code, lint exit code, fix verification result.

- **Verification** — post-stage check owned by FORGER (not the LLM). Runs project-specific commands (test, lint), checks file existence, auto-resolves gates. Each stage co-locates its own verification logic.

- **Worktree** — a git worktree created per run for isolation. Default on, opt-out via project config. Allows parallel runs without conflicts. Destroyed when run reaches terminal state; kept alive while run is blocked/parked.

- **change.md** — the state file for a run. YAML frontmatter (pipeline stage, gates, evidence, source properties, review state) + markdown body. Body contains the issue description written by intake (static after intake). Single source of truth for run progress.

- **Run Contract** — a shared markdown file inlined into every stage prompt by `prompt.py`. Defines LLM behavior rules: where to write output, file naming, what stages may/mustn't modify, change.md format. Single source of truth for "how to behave in a run."
