# FORGER Run Contract

Single source of truth for LLM behavior during a pipeline stage. All stage prompts load this contract.

## 1. Run directory layout

```
<run-dir>/
  change.md               # frontmatter = pipeline state, body = issue description
  <source-data>.*         # source data (varies by intake, e.g. sentry-snapshot.json)
  analysis.md             # analyze stage output
  proof.md                # prove stage output (test location + rationale)
  fix-options.md          # fix_options stage output (a/b/c options)
  issue.md                # draft stage output (GitHub issue body)
  commit.txt              # draft stage output (commit message)
  changelog.txt           # draft stage output
  pr.md                   # draft stage output (PR body)
  reviews/
    review-N-quality.md
    review-N-challenge.md
    review-N-feedback.md
```

## 2. Rules

- **Write only your stage's artifacts.** Do not modify files owned by other stages.
- **Read change.md for context** — frontmatter has pipeline state, evidence, gates. Body has issue description.
- **Use project commands** from the Run Context section below for test/lint execution.
- **Never modify `pipeline.stage`** — the harness verification handles all transitions. Exception: intake stages create the initial change.md and must set `pipeline.stage` to the intake's post-state.
- **Update `updated` timestamp** when modifying change.md frontmatter.
- **Evidence must be machine-captured** — exit codes from actual command runs, not claims.
- **Minimal comments in code.** Only explain non-obvious WHY, never WHAT. One short line max. No block comments, no multi-line docstrings for simple functions. If removing the comment wouldn't confuse a future reader, don't write it.

## 3. Stage artifact ownership

| Stage | Writes | Reads |
|---|---|---|
| {source}_intake | change.md (create) | source data |
| analyze | analysis.md, change.md (stack) | change.md body, source snapshot |
| prove | proof.md, change.md (evidence.proof_test) | analysis.md |
| fix_options | fix-options.md, change.md (gates.fix_choice) | analysis.md, proof.md |
| implement | code changes, change.md (evidence.fix_verified, evidence.lint) | fix-options.md, proof.md |
| review | reviews/review-N-{role}.md | all prior artifacts |
| draft | issue.md, commit.txt, changelog.txt, pr.md | all prior artifacts |
| push | change.md (github.issue, github.branch, github.pr) | issue.md, commit.txt, pr.md |

## 4. Evidence requirements

| Stage completes when | Evidence |
|---|---|
| proven | `evidence.proof_test.exit_code == 1` (test MUST fail to prove bug exists) |
| fix-chosen | `gates.fix_choice.resolved != null` |
| fixed | `evidence.fix_verified.exit_code == 0` AND `evidence.lint.exit_code == 0` |
| reviewed | `reviews/review-N-{role}.md` exists with `**Verdict:**` line |
| drafted | issue.md + commit.txt + changelog.txt + pr.md all exist |
