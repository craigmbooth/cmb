# Machine-readable output: `.cmb/audit/`

Alongside the human markdown report, every audit persists its findings as JSON
under a `.cmb/audit/` directory **at the root of the audited repo** (the user's
cwd, *not* the plugin). This is what lets a later run — or any other tool — pick
up where the last one left off and tell what changed.

There are two file shapes:

- `.cmb/audit/manifest.json` — one per audit: scorecard, scope, stack, run
  metadata, and a pointer to each dimension file.
- `.cmb/audit/<dimension>.json` — one per dimension that ran (`security.json`,
  `performance.json`, `best-practices.json`, `test-coverage.json`,
  `documentation.json`, `accessibility.json`, `design-system.json`,
  `infrastructure.json`, `observability.json`): the findings for that dimension.

`.cmb/audit/` holds **current state**, not history — each run overwrites it. The
dated markdown under `audit-reports/` is the historical record. The audited repo
should ignore `.cmb/audit/` in git (see SKILL.md step on gitignore).

The helper script `scripts/cmb_audit_store.py` produces and consumes exactly this
format (and computes IDs + the diff for you). The schema is specified here so the
format is also writable **by hand** when no shell/Python is available — both
paths must agree byte-for-byte on the ID rule below, or diffs across runs break.

## `manifest.json`

```json
{
  "schema_version": 1,
  "tool": "cmb:audit",
  "generated_at": "2026-05-25T22:40:00Z",
  "scope": "services/payments",
  "stack": ["python", "flask"],
  "commit": "41d0863",
  "overall_score": 6.5,
  "critical_present": true,
  "dimensions": {
    "security":      { "ran": true,  "score": 3, "headline": "Critical SQL injection in charge.py", "findings_file": "security.json", "counts": { "critical": 1, "high": 0, "medium": 2, "low": 1 } },
    "performance":   { "ran": true,  "score": 7, "headline": "One N+1 on the orders path",           "findings_file": "performance.json", "counts": { "critical": 0, "high": 0, "medium": 1, "low": 0 } },
    "accessibility": { "ran": false, "reason": "no frontend code in scope" }
  }
}
```

- `commit` — the audited repo's current short SHA if it's a git repo and you can
  get it; otherwise `null`.
- `overall_score` — mean of the dimension scores that ran, one decimal. `null` if
  nothing scored.
- `critical_present` — `true` if any ran dimension has ≥1 critical finding.
- A skipped dimension has `"ran": false` + a `reason`, and **no** findings file.

## `<dimension>.json`

```json
{
  "schema_version": 1,
  "dimension": "security",
  "generated_at": "2026-05-25T22:40:00Z",
  "scope": "services/payments",
  "score": 3,
  "headline": "Critical SQL injection in charge.py",
  "findings": [
    {
      "id": "security:charge.py:sql-injection:3f9a1c4e",
      "severity": "critical",
      "rule": "sql-injection",
      "title": "User input interpolated directly into SQL query",
      "file": "services/payments/charge.py",
      "line": 42,
      "evidence": "cur.execute(f\"... WHERE id = {user_id}\")",
      "recommendation": "Use a parameterized query: cur.execute(sql, (user_id,)).",
      "status": "new",
      "first_seen": "2026-05-25T22:40:00Z"
    }
  ]
}
```

Field notes:

- `severity` — one of `critical` · `high` · `medium` · `low` (same vocabulary the
  rubrics use).
- `rule` — a short, stable kebab-case slug for the *kind* of issue
  (`sql-injection`, `hardcoded-secret`, `n-plus-1`, `bare-except`,
  `missing-alt-text`, …). This is part of the identity of a finding, so keep the
  same slug for the same kind of problem across runs.
- `file` — path relative to the repo root, forward slashes. `line` may be `null`
  for whole-file findings.
- `evidence` — a short snippet or note proving the finding is real (grounding rule
  from SKILL.md still applies).
- `status` / `first_seen` — set by the diff step, see below. When writing a fresh
  file by hand, set `status` to `new` and `first_seen` to `generated_at` for any
  finding you can't match to a prior run.

## The finding `id` (stable across runs)

The diff works by matching findings between the prior `.cmb/audit/` and the
current one **by `id`**. So an id must be stable for "the same underlying issue"
even when its line number moves or its wording is tweaked. Therefore the id is
derived from things that *don't* drift — and deliberately **excludes the line
number and the title**.

```
key  = "<dimension>|<file>|<rule>|<locator>"      # all lowercased
id   = "<dimension>:<basename(file)>:<rule>:" + sha256(key).hexdigest()[:8]
```

- `<locator>` disambiguates multiple same-`rule` findings in the same file. Use a
  stable handle — a function/symbol name, or a 2–4 word gist (`"orders loop"`).
  Leave it empty (`""`) when `(dimension, file, rule)` is already unique in that
  file. Never put a line number in the locator.
- The human-readable prefix (`security:charge.py:sql-injection:`) is for eyeballing
  only; the 8-hex suffix from the full key is what guarantees uniqueness.

Get this rule exactly right in both the script and any by-hand write, or the same
issue will get different ids on consecutive runs and every finding will look
"new". The script is the safe path; hand-writing is the fallback.

## Diff semantics (read-back)

Given the **prior** `.cmb/audit/` (if present) and the **current** findings:

- **resolved** — id in prior, absent from current → the issue is gone (fixed, or
  no longer in scope). Resolved findings are *not* written to the new files; they
  appear only in the diff summary.
- **open** (carried over) — id in both → `status: "open"`, and `first_seen` is
  preserved from the prior file (so "open since 2026-05-01" is meaningful).
- **new** — id in current, absent from prior, **in a dimension that ran last
  time** → a genuine regression. `status: "new"`, `first_seen: <now>`.
- **newly_assessed** — id in current, absent from prior, **in a dimension that did
  *not* run last time** → not a regression, just surface that was never scored
  before (e.g. the prior run had no frontend in scope so accessibility was N/A,
  and now it runs). Still `status: "new"` in the file, but bucketed separately so
  the diff doesn't cry "10 new!" every time a conditional dimension switches on.
  This split needs the prior `manifest.json` to know which dimensions ran; if that
  can't be determined, everything falls back to **new**.

The diff summary the run should surface (chat + the report's "Changes since last
audit" section):

```json
{
  "had_prior": true,
  "prior_generated_at": "2026-05-01T10:00:00Z",
  "resolved":       [ { "id": "...", "dimension": "security", "severity": "high", "title": "..." } ],
  "new":            [ { "id": "...", "dimension": "security", "severity": "medium", "title": "..." } ],
  "newly_assessed": [ { "id": "...", "dimension": "accessibility", "severity": "high", "title": "..." } ],
  "open":           [ { "id": "...", "dimension": "security", "severity": "critical", "title": "...", "first_seen": "2026-05-01T10:00:00Z" } ],
  "counts": { "resolved": 1, "new": 1, "newly_assessed": 1, "open": 1 }
}
```

If there's no prior `.cmb/audit/`, `had_prior` is `false`, everything is `new`,
and `newly_assessed` is empty; say "first audit — no prior run to compare
against" rather than showing an empty diff.

## Conventions

- **`scope`** — the literal path audited, relative to the repo root (e.g.
  `services/payments`), or the string `"whole repository"` for a full-repo audit.
  Use the same convention every run so consecutive manifests are comparable. Scope
  is not part of a finding id, so a scope change never breaks matching.
- **`generated_at`** — let the helper script default it to the wall-clock instant
  (UTC, `...Z`). The `--now` flag exists only for deterministic tests; real runs
  don't pass it. The dated markdown filename (`cmb-audit-YYYY-MM-DD.md`) uses the
  date; `generated_at` is the precise instant — they won't be character-identical,
  and that's fine.
