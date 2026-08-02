# Draft

## Purpose

Produce deliverable files for push. Transition: `reviewed` → `drafted`. Pure transcription from existing artifacts.

## Procedure

1. Read ALL run artifacts: analysis.md, proof.md, fix-options.md, reviews/, change.md.
2. Write `issue.md`: first line is `# <title>` (push harness takes line 1 for `gh --title`). Body: what happens, steps to reproduce, root cause summary, source reference/link.
3. Write `commit.txt`: subject line + body summarizing root cause and fix.
4. Write `changelog.txt`: one line describing the fix.
5. Write `pr.md`: first line `# <title>`. Body: problem, root cause, chosen option + why, proof test (red→green), verification evidence. Check review files in `reviews/` — if any reviewer verdict is `warned`, add `## Review notes (overridden)` section listing warned findings.
6. Bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- `issue.md`, `commit.txt`, `changelog.txt`, `pr.md`

## Never

- Never invent content not grounded in run artifacts.
- Never write placeholder values.
- Never omit warned review findings from pr.md.
- Never touch application code, tests, or git.
