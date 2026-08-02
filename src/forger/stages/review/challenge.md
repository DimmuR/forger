# Challenge Review

## Purpose

Devil's advocate review: actively try to break the implementation. Write verdict to `reviews/review-{N}-challenge.md`.

## Procedure

1. Determine review round N: count `review-*-feedback.md` files in `reviews/` directory, add 1.
2. Review the diff with an adversarial mindset:
   - **Edge cases**: inputs the fix doesn't handle (nulls, empty, concurrent, large).
   - **Regression risk**: does the fix break any existing behavior?
   - **Assumption validation**: are the fix's assumptions about data/state correct?
   - **Error paths**: what happens when the fix's dependencies fail?
   - **Alternative scenarios**: could this bug manifest differently than the proof test shows?
3. Write `reviews/review-{N}-challenge.md`: each finding named with severity and concrete failure scenario.
4. End the review file with exactly one of these verdict lines:
   - `**Verdict: accepted**` — no realistic failure scenarios found
   - `**Verdict: warned**` — theoretical concerns but unlikely in practice
   - `**Verdict: changes_requested**` — concrete failure scenarios identified

## Outputs

- `reviews/review-{N}-challenge.md`

## Never

- Never modify application code or tests — review writes review artifacts only.
- Never modify change.md — the verify harness handles status transitions.
- Never reject for style or convention — that's the quality reviewer's domain.
- Never write speculative findings without a concrete failure scenario.
