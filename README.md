# Concurrent Multi-pass Bot (cmb)

**Concurrent Multi-pass Bot** (`cmb`) is Craig's personal Claude Code plugin
marketplace.

This repo is **both a marketplace and a plugin**. The Concurrent Multi-pass Bot
(`cmb`) plugin ships two skills that work as a pair — audit reviews, fix acts:

- **`cmb:audit`** — a multi-dimensional, parallel codebase audit. It fans out one
  reviewer per quality dimension (security, performance, best practices, test
  coverage, plus accessibility/design-system when frontend code is present and
  infrastructure when IaC is present), then returns a 0–10 scorecard per dimension
  and a severity-ranked list of findings, saved as a dated markdown report under
  `audit-reports/` and as machine-readable JSON under `.cmb-audit/`. On a re-run it
  diffs against the last `.cmb-audit/` to show what's fixed, new, or still open. It
  reads and scores — it does not modify code. Runs **only** when you explicitly
  type `/cmb:audit` (optionally with a path).
- **`cmb:fix`** — the companion fixer. It reads the audit's `.cmb-audit/` findings,
  summarizes them, lets you choose which categories and which specific findings to
  fix, then makes the edits and runs your tests. It edits the working tree but does
  **not** commit and does **not** touch `.cmb-audit/`; afterward you re-run
  `/cmb:audit` to confirm the fixes show up as resolved. If no audit has been run
  it says so and points you at `/cmb:audit` rather than guessing. Runs **only** when
  you explicitly type `/cmb:fix` (optionally with a category, e.g. `/cmb:fix security`).

Typical loop: `/cmb:audit` → review → `/cmb:fix` → re-run `/cmb:audit` to verify.

## Install

```
/plugin marketplace add craigmbooth/cmb
/plugin install cmb@cmb
```

Then restart Claude Code. Verify with:

```
/cmb:audit <path>
```

## Layout

```
.claude-plugin/marketplace.json   # marketplace manifest (lists the cmb plugin)
plugins/cmb/
  .claude-plugin/plugin.json      # plugin manifest
  skills/audit/
    SKILL.md                      # the cmb:audit skill
    references/                    # per-dimension scoring rubrics + output-schema.md
    scripts/cmb_audit_store.py    # writes .cmb-audit/ JSON + computes the cross-run diff
    evals/                        # skill evals + fixtures
  skills/fix/
    SKILL.md                      # the cmb:fix skill (consumes .cmb-audit/)
    evals/                        # skill evals + fixtures
```

## Adding a dimension or skill

- New audit dimension: add `plugins/cmb/skills/audit/references/<dimension>.md`
  and wire it into the dispatch list in `SKILL.md`.
- New `cmb:*` skill: add `plugins/cmb/skills/<name>/SKILL.md`.
