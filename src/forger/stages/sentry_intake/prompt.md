# Sentry Intake

## Purpose

Fetch Sentry issue data, create the initial run state. Transition: nothing → `triaged`.

## Procedure

1. **Fetch issue data using Sentry MCP tools.** Call the Sentry MCP tools to get:
   - Issue details (title, error message, first/last seen, event count, user count)
   - Latest events with full stack traces and breadcrumbs
   - Tags and context
   Write the raw fetched data to `sentry-snapshot.json` in the run directory.

2. **Write `change.md`** with this exact frontmatter structure:
   ```yaml
   ---
   id: sentry-<ISSUE-ID>
   title: "<error title from Sentry>"
   origin: sentry
   created: "<YYYY-MM-DD>"
   updated: "<YYYY-MM-DD>"
   pipeline:
     stage: triaged
     parked_reason: null
   gates: {}
   evidence: {}
   github:
     issue: null
     branch: null
     pr: null
   ---
   ```
   - Body: 2-3 paragraph description — what's happening, where, impact.

3. Ensure `pipeline.stage` is set to `triaged` in the YAML template above — the harness verifies this value.

## Outputs

- `sentry-snapshot.json` (raw Sentry data)
- `change.md` (created)

## Never

- Never implement fixes or write code.
- Never modify existing run artifacts.
- Never skip the snapshot write — downstream stages need it.
