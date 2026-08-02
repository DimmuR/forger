# Draft

## Purpose

Produce deliverable files for push. Transition: `reviewed` → `drafted`. Pure transcription from existing artifacts.

## Procedure

1. Read ALL run artifacts: analysis.md, proof.md, fix-options.md, reviews/, change.md.
2. Write `issue.md`: first line is `# <title>` (push harness takes line 1 for `gh --title`).
   Title must be a user-perspective symptom — what the user cannot do or what breaks.
   Never use raw exception class names or error types as the title.
   Body sections:
   - **What happens** — 2-3 sentences describing the user-visible symptom only.
     No internal class names, no framework details, no impact stats.
   - **Steps to reproduce** — Two tiers in one section:
     First, **Possible manual trigger** (numbered UI-level steps) when a manual path
     can be inferred. Then **Technical** (API calls, CLI commands, or background task
     triggers) — always present regardless of whether manual steps exist.
   - **Root cause** — 1-2 sentences in narrative style. May reference handler/function
     names and key calls inline, but no line numbers and no full file paths.
     Detail belongs in the PR, not here.
   - If a source tracking link is available (e.g. Sentry issue URL), include it
     at the bottom as `**Sentry:** <url>` or `**Source:** <url>`.
3. Write `commit.txt`: subject line + body summarizing root cause and fix.
4. Write `changelog.txt`: one line describing the fix.
5. Write `pr.md`: first line is `# <title>` (push harness takes line 1 for `gh --title`).
   Title must start with `fix:` followed by the user-perspective symptom from the issue
   title (echo it, don't rephrase into implementation jargon).
   Body sections:
   - `Closes #<issue-number>` — standalone line linking to the issue. No problem
     restatement; the issue already describes the symptom.
   - **Root cause** — 3-5 sentences in narrative style. May reference file paths and
     handler/function names inline, but no line numbers. Explain the call chain that
     leads to the failure clearly enough that a reviewer unfamiliar with the code
     can follow it.
   - **Fix** — 2-3 sentences describing what was changed and why this approach.
     No option letters, no rejected alternatives, no comparison table.
   - **Proof test** — one line per test. Format:
     `\`test_name\`` — fails before fix (`ExceptionName`), passes after.
   Do not include: verification evidence, impact stats, option comparisons,
   review override notes, or environment names.
6. Bump `updated`. Do NOT modify `pipeline.stage` — the harness handles transitions.

## Outputs

- `issue.md`, `commit.txt`, `changelog.txt`, `pr.md`

## Never

- Never invent content not grounded in run artifacts.
- Never write placeholder values.
- Never restate the problem in pr.md — the linked issue covers it.
- Never touch application code, tests, or git.
