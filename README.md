# Concurrent Multi-pass Bot (cmb)

**Concurrent Multi-pass Bot** (`cmb`) is Craig's personal Claude Code plugin
marketplace.

This repo is **both a marketplace and a plugin**. The Concurrent Multi-pass Bot
(`cmb`) plugin currently ships one skill:

- **`cmb:audit`** — a multi-dimensional, parallel codebase audit. It fans out one
  reviewer per quality dimension (security, performance, best practices, test
  coverage, plus accessibility/design-system when frontend code is present and
  infrastructure when IaC is present), then returns a 0–10 scorecard per dimension
  and a severity-ranked list of findings, saved as a dated markdown report under
  `audit-reports/`. It reads and scores — it does not modify code. It runs **only**
  when you explicitly type `/cmb:audit` (optionally with a path).

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
    references/                    # per-dimension scoring rubrics
    evals/                         # skill evals + fixtures
```

## Adding a dimension or skill

- New audit dimension: add `plugins/cmb/skills/audit/references/<dimension>.md`
  and wire it into the dispatch list in `SKILL.md`.
- New `cmb:*` skill: add `plugins/cmb/skills/<name>/SKILL.md`.
