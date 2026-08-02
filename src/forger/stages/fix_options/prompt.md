# Fix Options

## Purpose

Propose fix options and resolve the gate. Transition: `proven` → `fix-chosen`.

## Procedure

1. Read `analysis.md` and `proof.md` fully.
2. Design options grounded in the root cause:
   - **(a) minimal** — smallest diff that makes the proof test pass. Fixes symptom, not always the root.
   - **(b) structural** — fixes root cause at the right abstraction. Creates the function/constant/boundary that makes future similar bugs trivial to handle.
   - **(c) comprehensive** — (b) plus fixes all equivalent entry points, adds defensive validation, or addresses the broader category of the bug.
   If options are genuinely identical, say so — one option with a stated reason beats three fake ones. If (b) and (c) collapse, state why.
3. For each option: scope of diff (files touched), risk, what it does NOT fix, follow-up debt.
4. Write `fix-options.md` with the options and a recommendation.
5. Resolve the gate: auto-select the recommended option. Set `gates.fix_choice.resolved` to the option letter + rationale. Bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- `fix-options.md`

## Never

- Never implement anything — analysis and proposal only.
- Never fabricate tradeoffs to make options look distinct.
