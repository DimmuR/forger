# Implement

## Purpose

Apply the chosen fix option. Transition: `fix-chosen` → `fixed`. Verification is command output, not judgment.

## Procedure

1. Read `fix-options.md` — the resolved option is the spec. Also read `analysis.md` and `proof.md`.
2. If a review loop-back: read latest `reviews/review-*-feedback.md` — its items are additional spec.
3. Implement the resolved option exactly as specified.
4. Run the proof test using the `test_file` project command (see Run Context). Must pass (exit code 0). If not, iterate on the fix.
5. Run the affected test suite using the `test` project command. Must pass.
6. Run lint using the `lint` project command. Must pass.
7. Record evidence with one-line `summary` (what passed/failed, e.g. "3 tests pass, 0 fail" or "AssertionError in test_foo"):
   - `evidence.fix_verified`: path, exit_code, last_run, summary
   - `evidence.lint`: exit_code, last_run, summary
8. Commit all application code changes: `git add -u && git commit -m "fix: <brief symptom-level description>"`. Use conventional commit format — the subject must describe what the fix does from a user perspective, not reference option letters or internal jargon. Only stage tracked files — do not use `git add -A` to avoid picking up stray untracked files. If you created new files, add them explicitly by path. This preserves work across review loop-backs.
9. Bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- Application code changes, committed with conventional commit message (`fix: <description>`)
- `fix-options.md` gains `## Implementation notes` (only if deviations)

## Before writing code, answer:

1. Where does untrusted data enter? Fix THERE, not downstream.
2. If this bug recurs with different input, does my fix already handle it?
3. Does a function or abstraction for this already exist in the codebase? Use it or extend it.
4. Am I matching the idiom within 50 lines of my change?
5. Would a reviewer ask "why not just...?" — if yes, do that instead.

## Never

- Never skip test AND lint runs — evidence exit codes are required for the harness to advance.
- Never modify the proof test to make it pass.
- Never expand scope beyond the resolved option.
- Never implement an option other than the resolved one.
