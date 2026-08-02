# Quality Review

## Purpose

Review the implementation for correctness and conventions. Write verdict to `reviews/review-{N}-quality.md`.

## Procedure

1. Determine review round N: count `review-*-feedback.md` files in `reviews/` directory, add 1.
2. Review the diff (read changed files, run `git diff`):
   - **Correctness vs analysis**: does the diff fix the ROOT CAUSE, or the symptom?
   - **Proof honesty**: proof test still asserts correct behavior (not weakened)?
   - **Conventions**: patterns match surrounding module.
   - **Blast radius**: callers/consumers of changed code inspected.
   - **Scope**: nothing in the diff that fix-options.md doesn't account for.
3. Write `reviews/review-{N}-quality.md`: each finding named with severity and concrete consequence.
4. End the review file with exactly one of these verdict lines:
   - `**Verdict: accepted**` — no findings
   - `**Verdict: warned**` — findings acceptable if human agrees
   - `**Verdict: changes_requested**` — findings warrant changes

## Outputs

- `reviews/review-{N}-quality.md`

## Never

- Never modify application code or tests — review writes review artifacts only.
- Never modify change.md — the verify harness handles status transitions.
- Never approve findings this same review raised without them being addressed.
- Never write generic findings ("could be cleaner") — name it or drop it.
