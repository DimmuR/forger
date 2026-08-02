# Analyze

## Purpose

Perform root-cause analysis. Transition: `triaged` → `analyzed`. Produces the root cause with file:line evidence.

## Procedure

1. Read `change.md` body for issue context. If source data files exist in the run directory (e.g. `sentry-snapshot.json`), read those for additional raw data.
2. Search the codebase to locate the root cause. Use stack traces (if available in source data), error messages, and code search to find the exact file and line.
3. Synthesize the root cause: WHERE the bug lives (file:line), WHY the bad state arises, WHAT the trigger conditions are. If root cause cannot be localized to a specific file:line after reading the codebase, park the run with a reason explaining what was searched and what was found.
4. Determine stack from root cause files. Set `pipeline.stack` to match a key in the project's configured commands (visible in Run Context below), or leave unset if unclear.
5. Write `analysis.md` with sections: Root Cause (file:line refs), Trigger Conditions, Evidence, Blast Radius, Reproduction Sketch (what a failing test should assert).
6. Update `change.md` frontmatter: set `pipeline.stack` if determined, bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- `analysis.md`

## Never

- Never write fixes, tests, or any code — analysis only.
- Never present a hypothesis as a conclusion; if you cannot find a concrete file:line, park the run.
- Never modify application code.
