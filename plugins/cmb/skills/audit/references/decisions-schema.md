# Per-finding decisions: `.cmb/decisions.json`

Alongside the machine-regenerable `.cmb/audit/` state, every repo can carry a
**committed** decisions file that records what the team has chosen to do with
specific findings — beyond just "fix it now" / "fix it later." It is the only
piece of cmb state that is **not** gitignored, because the choices in it are
team-shared judgments, not regenerable tool output.

`cmb:triage` is the only canonical writer. `cmb:audit` reads it to fold decisions
into the report; `cmb:fix` reads it to skip findings the user has put a verb on.
Hand-editing is fully supported — the format below is the contract.

## Path & gitignore

- File: `.cmb/decisions.json` at the root of the audited repo (sibling to
  `.cmb/audit/`).
- The audited repo's `.gitignore` should exclude `.cmb/audit/` but **not**
  `.cmb/decisions.json`. The conventional shape:

  ```
  .cmb/audit/
  !.cmb/decisions.json
  ```

## File shape

```json
{
  "schema_version": 1,
  "tool": "cmb:triage",
  "decisions": {
    "security:main.py:hardcoded-secret:abc12345": {
      "verb": "accept-risk",
      "decided_at": "2026-05-26T20:00:00Z",
      "decided_by": "craig",
      "justification": "Dev-only seed; prod rotates via Secret Manager.",
      "severity_at_decision": "critical",
      "title_at_decision": "Hardcoded super-administrator password seeded on every startup",
      "expires_at": "2026-09-01T00:00:00Z"
    },
    "performance:document.py:n-plus-one:5c033067": {
      "verb": "plan",
      "decided_at": "2026-05-25T22:00:00Z",
      "justification": "Pagination + bulk metadata fetch tracked in Q3 perf sprint.",
      "plan_file": "audit-reports/perf-list-user-documents.md",
      "severity_at_decision": "high",
      "title_at_decision": "list_user_documents fetches file metadata per document on the dashboard"
    },
    "documentation:README.md:doc-drift:7f30a012": {
      "verb": "dismiss",
      "decided_at": "2026-05-26T20:05:00Z",
      "justification": "False positive — reviewer read stale state; README port already fixed.",
      "severity_at_decision": "high",
      "title_at_decision": "README run instructions point at the wrong app port"
    }
  }
}
```

The top-level `decisions` map is **keyed by finding `id`** — the same id format
that `cmb_audit_store.py` produces (`<dimension>:<basename>:<rule>:<sha8>`). That
mapping is what gives an exact match-or-no-match per finding across runs.

## The verbs

Exactly three verbs are persisted:

| Verb | Semantics | Effect on audit | Effect on `cmb:fix` |
|---|---|---|---|
| `plan` | Real issue, too big to fix inline. See `plan_file`. | Reported with 🗺 marker + link; not in Top Priorities. | Excluded from inline-fix menu; appears in a "Planned (refresh plan only)" bucket. |
| `accept-risk` | We know, we're OK with it. | Suppressed from Top Priorities and per-dimension lists; moved to a fold at the bottom of the report. | Hidden from the menu. |
| `dismiss` | False positive / not a real issue. | Omitted from the human report entirely. | Hidden from the menu. |

`fix` is **not** persisted per finding: a "fix it next time" decision becomes
irrelevant the moment the next `cmb:fix` resolves it. "Always fix this *kind* of
issue without asking" is per-rule policy — a future `cmb-policy.toml` surface,
out of scope here.

## Required fields per decision

All decisions:
- `verb`: one of `"plan"`, `"accept-risk"`, `"dismiss"`.
- `decided_at`: UTC ISO timestamp, `"...Z"`.
- `severity_at_decision`: `"critical" | "high" | "medium" | "low"` — captured so
  **escalation** works (see below).
- `title_at_decision`: the finding title at decision time — cached so a human
  reading this file knows what's being decided without cross-referencing
  `.cmb/audit/`.
- `justification`: free text. **Required for `accept-risk` and `dismiss`** (a
  decision to suppress without a reason is the wrong kind of decision). Optional
  but strongly recommended for `plan`.

Optional fields:
- `decided_by`: free-form string (`git config user.name`, an email, a handle —
  not enforced).
- `plan_file`: path (relative to repo root) to a remediation doc. Only meaningful
  for `verb: "plan"`.
- `expires_at`: UTC ISO timestamp. Only meaningful for `verb: "accept-risk"` —
  after this, the decision is treated as expired and the finding re-surfaces.

## The safety valves: escalation and expiry

A decision is **voided for the current run** (the finding re-surfaces, tagged so
the user sees what happened) when *any* of these is true:

- **Escalation** — current severity is worse than `severity_at_decision`.
  Suppressing a `medium` doesn't suppress a `critical` future incarnation of the
  same finding.
- **Expiry** — `expires_at` is present and in the past.

Voided decisions are reported with a `🚨 ESCALATED` or `⏰ EXPIRED` tag in the
audit's "Decisions" section so the user re-triages with the new context.

## Slug drift (the orphan rule)

The `id` is derived from `(dimension, file, rule, locator)`. If a reviewer
re-slugs the same problem in a later run (e.g. `missing-object-authz` →
`broken-access-control`), the id changes and the previous decision becomes an
**orphan**: a key in `.cmb/decisions.json` that no longer matches any current
finding.

The audit surfaces orphans in its summary ("1 decision no longer matches any
current finding — consider `cmb:triage --relink`"). It does **not** delete
them, and does **not** silently fuzzy-match — those choices are deliberately the
user's, via `cmb:triage --relink <old-id> <new-id>`.

## Lifecycle: who reads, who writes

- `cmb:triage` — the **only** canonical writer. Atomic writes (temp + rename).
- `cmb:audit` — reads `.cmb/decisions.json` after persisting findings, applies
  decisions to its diff, narrates them in the report. Never writes.
- `cmb:fix` — reads `.cmb/decisions.json` to filter the interview. **May write**
  when the user explicitly chooses "defer this with a plan" mid-fix (which is
  semantically a `triage` call). The write is always behind an explicit user
  prompt — `cmb:fix` never decides on the user's behalf.

## Hand-editing

This file is JSON because hand-editing is a first-class workflow. To dismiss a
finding by hand, copy its id out of `.cmb/audit/<dimension>.json`, add an entry
with `verb: "dismiss"` + a justification + `severity_at_decision` + a sensible
`title_at_decision`, save. The next `cmb:audit` reflects it. The helper script
`scripts/cmb_triage_store.py` validates the file on every read and will report a
clear error if a required field is missing or a verb is unrecognized.
