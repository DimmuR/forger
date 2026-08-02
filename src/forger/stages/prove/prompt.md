# Prove

## Purpose

Write a failing test that captures the bug. Transition: `analyzed` → `proven`. Fixes nothing.

## Procedure

1. Read `analysis.md` — the Reproduction Sketch is the spec for the test.
2. Locate the right test file (extend existing module test file when one exists; create alongside otherwise, matching naming conventions).
3. Write ONE test that fails BECAUSE of the root cause — asserting the correct behavior, not asserting the bug.
4. Run the test using the project test command. Capture exit code.
   - Exit code 0 (passes) → the test does not capture the bug. Revise once. If still green, report blocked.
   - Exit code 1 with expected failure → proceed.
5. Write `proof.md`: what the test asserts, why it proves the root cause, exact run command, observed failure output.
6. Update `change.md` frontmatter: set `evidence.proof_test` (path, last_run, exit_code: 1), bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- Test file (the ONLY code this stage writes)
- `proof.md`

## Never

- Never skip capturing an exit code from a test run — evidence is required for the harness to advance.
- Never fix the bug or weaken the assertion to force a red.
- Never touch application code — test files only.
