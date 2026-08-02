# Configuration

Config loads with precedence: **built-in → global → project**. Each layer deep-merges into the previous.

| Location | Scope |
|---|---|
| Built-in defaults | Hardcoded in `config.py` |
| `~/.forger/config.yaml` | All projects |
| `<project>/.forger/config.yaml` | This project only |

## Top-level keys

### `default_runner`

Which runner to use when a stage or reviewer doesn't specify one.

```yaml
default_runner: claude   # default
```

### `base_branch`

Branch that PRs target and worktrees branch from.

```yaml
base_branch: main   # default
```

### `branch_prefix`

Prefix for worktree branch names. Branches created as `{prefix}/{issue_id}`.

```yaml
branch_prefix: forger   # default
```

### `worktree`

Run code-modifying stages in an isolated git worktree.

```yaml
worktree: true   # default
```

### `gh_account`

GitHub account/org for PR creation. Optional.

```yaml
gh_account: my-org
```

---

## `models`

Model selection per stage. Stage-specific overrides take priority over `default`.

```yaml
models:
  default: sonnet
  stages:
    sentry_intake: opus
    analyze: sonnet
    prove: sonnet
    fix_options: sonnet
    implement: sonnet
    review: opus
    draft: sonnet
```

Reviewer-level `model` overrides (see `review.reviewers`) take priority over `models.stages.review`.

---

## `runners`

Named runner templates. Command is a shell string with placeholders:

| Placeholder | Value |
|---|---|
| `{model}` | Resolved model name |
| `{prompt_arg}` | Path to temp file containing rendered prompt |
| `{workdir}` | Working directory (repo or worktree) |
| `{allowed_tools}` | Comma-separated tool list |

`env` values also support `{model}` substitution.

```yaml
runners:
  claude:
    command: "claude -p {prompt_arg} --model {model} --allowedTools {allowed_tools} --output-format json --verbose"
    timeout: 900
  goose:
    command: "goose run --no-session --with-builtin developer -t {prompt_arg}"
    env:
      GOOSE_PROVIDER: ollama
      GOOSE_MODEL: "{model}"
    timeout: 900
```

### Runner fields

| Field | Type | Default | Description |
|---|---|---|---|
| `command` | string | required | Shell command template |
| `env` | dict | `{}` | Extra environment variables |
| `timeout` | int | `900` | Seconds before runner is killed |

---

## `tools`

Allowed tools per stage. Controls what the runner can access.

```yaml
tools:
  default: [Read, Write, Edit, Bash]
  stages:
    sentry_intake: [Read, Write, Edit, Bash, mcp__sentry]
    review: [Read, Write, Edit]
    draft: [Read, Write, Edit]
```

---

## `review`

Multi-reviewer configuration. Omit entirely for default behavior (single quality reviewer, `all` consensus).

```yaml
review:
  consensus: all
  reviewers:
    - role: quality
    - role: challenge
      runner: goose
      model: glm-4-32b
```

### `review.consensus`

How individual reviewer verdicts combine into a final decision.

| Value | Behavior |
|---|---|
| `all` | Every reviewer must accept/warn. One rejection blocks. **(default)** |
| `majority` | More than half must accept/warn. |

### `review.reviewers`

List of reviewer definitions. Each reviewer runs independently with its own prompt, runner, and model.

| Field | Type | Default | Description |
|---|---|---|---|
| `role` | string | `quality` | Determines prompt file (`{role}.md` in review stage dir, falls back to `prompt.md`) and output naming (`review-{N}-{role}.md`) |
| `runner` | string | `null` | Runner name from `runners` dict. Falls back to `default_runner` |
| `model` | string | `null` | Model override. Falls back to `models.stages.review` |

Built-in roles:
- **quality** — correctness, conventions, blast radius, scope (uses `prompt.md`)
- **challenge** — devil's advocate: edge cases, regression risk, assumption validation (uses `challenge.md`)

Custom roles work if you provide a matching `{role}.md` prompt file in `.forger/stages/review/`.

### Review artifacts

Each round N produces:
- `reviews/review-{N}-{role}.md` — per-reviewer verdict and findings
- `reviews/review-{N}-feedback.md` — combined feedback (only on `changes_requested`, written by verify harness)

---

## `commands`

Project-specific commands injected into stage prompts. Tells the LLM how to run tests, lint, etc.

Values can be flat strings or stack-aware dicts. Stack is detected by the analyze stage and stored in `pipeline.stack`.

**Flat (all stacks):**
```yaml
commands:
  test: "pytest"
  lint: "ruff check ."
```

**Stack-aware:**
```yaml
commands:
  test:
    _default: "pytest"
    frontend: "vitest run"
  lint:
    _default: "ruff check ."
    frontend: "eslint ."
```

**Mixed (some flat, some stack-aware):**
```yaml
commands:
  test:
    _default: "pytest"
    frontend: "vitest run"
  format: "black ."
```

Resolution: stack-specific value wins → `_default` fallback → flat string. Commands without a matching key are omitted.

---

## `.forger/guidelines.md`

Not part of `config.yaml`. A separate markdown file injected into every stage prompt. Use it for project-specific rules the LLM should follow.

```markdown
- Do not use try/except in tests
- All new endpoints need OpenAPI schema
- Use `get_object_or_404`, never raw `.get()` with manual 404
```

---

## Example: full project config

```yaml
base_branch: develop
worktree: true
gh_account: my-org

models:
  default: sonnet
  stages:
    review: opus

runners:
  claude:
    command: "claude -p {prompt_arg} --model {model} --allowedTools {allowed_tools} --output-format json --verbose"
    timeout: 1200
  goose:
    command: "goose run --no-session --with-builtin developer -t {prompt_arg}"
    env:
      GOOSE_PROVIDER: ollama
      GOOSE_MODEL: "{model}"
    timeout: 600

review:
  consensus: all
  reviewers:
    - role: quality
      runner: claude
      model: opus
    - role: challenge
      runner: goose
      model: glm-4-32b

commands:
  test: "just backend test"
  lint: "just backend lint"
```
