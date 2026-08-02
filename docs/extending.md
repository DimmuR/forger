# Extending Forger

How to add new pipeline stages and intake sources. Read alongside `src/forger/stages/run_contract.md` for the full LLM contract.


## Stage anatomy

Each stage lives in `src/forger/stages/<name>/` with:

- **`prompt.md`** -- instructions given to the LLM. Written as plain Markdown. The prompt renderer appends the shared run contract, project guidelines, and a Run Context block with run directory, repo root, current stage, and resolved project commands. No Jinja -- the prompt is static text; runtime context arrives in the appended block.

- **Verify logic** -- one of two approaches:
  - **Declarative** (preferred for simple stages): a `VerifyCheck` spec on the `StageSpec` in `pipeline.py`. Declares required files, evidence exit codes, and gate checks. The framework generates the verify function automatically.
  - **Custom `verify.py`** (for complex stages): a Python module exporting `def verify(run_dir: Path, config: ProjectConfig) -> bool`. Use when the stage needs non-linear flow (review loopback, push orchestration, intake validation).

Optional: a `references/` subdirectory with `.md` files. These are appended to the prompt automatically as reference material.


## Declarative verify

Most stages check simple post-conditions: files exist, evidence has expected exit codes, gates are resolved. Declare these in the `StageSpec`:

```python
StageSpec(
    name="prove",
    pre_state="analyzed",
    post_state="proven",
    label="Proven",
    artifacts=["proof.md"],
    verify=VerifyCheck(
        required_files=("proof.md",),
        evidence_checks=(("proof_test", 1),),
    ),
)
```

`VerifyCheck` fields:
- `required_files` -- files that must exist in `run_dir`
- `evidence_checks` -- `(evidence_key, expected_exit_code)` pairs
- `gate_resolved` -- gate key that must have a non-None `resolved` value

The framework handles terminal/parked guards, pre-state checks, idempotency, and state transitions automatically.


## Custom verify.py

For stages with complex flow control, write a `verify.py`. Every custom verify follows this skeleton:

1. **Terminal/parked guard** -- if `pipeline.stage` is in `TERMINAL_STAGES` or `parked_reason` is set, return `False` immediately. Use `check_stage_guards()` for this.
2. **Artifact check** -- confirm expected output files exist.
3. **Evidence check** (when applicable) -- verify machine-captured evidence in `change.md` frontmatter.
4. **Transition** -- set `state.pipeline.stage` to the post-state and call `save_change()`. Return `True`.

Non-linear transitions (loop-backs, parking) are encoded in verify, not in the orchestrator. Review's verify, for example, loops back to `fix-chosen` on rejection and parks after exceeding a retry limit.


## Adding a new stage

1. **Create the directory**: `src/forger/stages/<name>/`

2. **Write `prompt.md`**: describe purpose, procedure, outputs, and constraints. The LLM receives the run contract and context block automatically -- don't duplicate that. End with a "Never" section listing what the LLM must not do.

3. **Register in `pipeline.py`**: add a `StageSpec` entry to the `STAGES` tuple in the correct position. Fields:
   - `name` -- matches the directory name
   - `pre_state` -- the pipeline state that triggers this stage
   - `post_state` -- the state after successful completion
   - `label` -- human-readable label for display
   - `artifacts` -- list of files/dirs the stage produces (used for reporting, not enforcement)
   - `verify` -- a `VerifyCheck` for declarative stages, or `None` if using a custom `verify.py`

   The derived lookup tables (`STAGE_BY_NAME`, `STAGE_BY_PRE_STATE`, etc.) rebuild automatically from `STAGES`.

4. **Write `verify.py`** (only if the stage needs custom logic). For simple stages, step 3's `VerifyCheck` is sufficient.

5. **Configure defaults** (optional): in `config.py`'s `BUILTIN_DEFAULTS`, add entries under `models.stages` and `tools.stages` if the stage needs a non-default model or tool set.


## Adding a new source/intake

A source is just a specially named intake stage. To add a `github` source:

1. Create `src/forger/stages/github_intake/` with `prompt.md` and `verify.py`.

2. The intake stage must produce a `change.md` with valid YAML frontmatter matching the `ChangeState` model. Required fields:
   - `id` -- unique identifier (convention: `<source>-<issue-id>`)
   - `title` -- short description
   - `origin` -- source name (e.g. `github`)
   - `created`, `updated` -- ISO date strings
   - `pipeline.stage` -- must be set to the intake's post-state (e.g. `triaged`)

   Source-specific data goes in `pipeline.source_properties` (a free-form dict) or in dedicated model sections like `sentry` and `github` on `ChangeState`.

3. Register in `pipeline.py`'s `STAGES` tuple. The intake stage's `name` must follow the `<source>_intake` convention so the orchestrator can resolve it from the source name.

4. The stage resolution system (`stages/__init__.py`) supports **source-specific overrides**: for a source named `github`, a stage directory `github_analyze` takes priority over `analyze`. This lets you customize downstream stages per source without touching the generic ones.


## Stage resolution order

When the orchestrator needs a stage definition, `resolve_stage()` searches in order:

1. `<project>/.forger/stages/<source>_<stage>/` -- project-level, source-specific
2. `<project>/.forger/stages/<stage>/` -- project-level, generic
3. `src/forger/stages/<source>_<stage>/` -- package-level, source-specific
4. `src/forger/stages/<stage>/` -- package-level, generic

First match with a `prompt.md` or `verify.py` wins. Stages using declarative `VerifyCheck` only need `prompt.md`. This lets projects override built-in stages without forking.


## Where config fits in

Configuration merges with precedence: built-in defaults < `~/.forger/config.yaml` < `<project>/.forger/config.yaml`.

Key config areas for extending:

- **`default_runner`** / **`runners`** -- which LLM runner command template to use. Built-in runners: `claude`, `goose`.
- **`models.stages`** -- per-stage model override (e.g. `sentry_intake: opus`).
- **`tools.stages`** -- per-stage tool allowlist (e.g. intake gets Sentry MCP tools, review gets read-only tools).
- **`commands`** -- project commands (test, lint) injected into prompt context. Supports per-stack overrides.
- **`review`** -- reviewer definitions (role, runner, model) and consensus mode (`all` or `majority`).


## The verify-owns-transitions principle

The LLM never sets `pipeline.stage` (exception: intake stages, which create the initial `change.md`). The verify module sets the stage after confirming artifacts and evidence. The orchestration loop is deliberately simple -- it calls the runner, calls verify, and either continues or stops. All branching logic (loop-backs, conditional parking, skipping) lives in verify, co-located with the stage that needs it.

This means adding a stage with custom flow control requires zero changes to the orchestrator. Just encode the logic in your verify.
