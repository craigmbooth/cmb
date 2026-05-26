---
name: triage
description: >-
  Concurrent Multi-pass Bot (cmb) — per-finding triage. Walks the findings
  recorded by /cmb:audit and lets the user assign a durable decision (plan /
  accept-risk / dismiss) with a justification. Decisions are written to
  .cmb/decisions.json (committed source of truth — unlike .cmb/audit/, which
  is gitignored tool state). On subsequent runs, cmb:audit folds these
  decisions into the report (suppressed items move to a fold; planned items
  carry a 🗺 marker; escalations and expirations resurface with a tag) and
  cmb:fix skips items the user has already decided on. INVOCATION: this skill
  runs ONLY when the user explicitly types the /cmb:triage slash command. Do
  NOT trigger it automatically — phrases like "ignore this finding" or
  "we'll fix that later" should NOT invoke it on their own. Wait for the
  explicit /cmb:triage command.
---

# cmb:triage — Concurrent Multi-pass Bot

Walk the findings recorded by `/cmb:audit` and assign each a durable verb:
**plan**, **accept-risk**, **dismiss** — with a justification. The decisions
land in `.cmb/decisions.json` at the audited-repo root, a committed file that
both `cmb:audit` and `cmb:fix` respect on every future run.

This is the *decision* skill, not the *fixer*. It reads `.cmb/audit/`, lets
the user pick a verb per finding, writes `.cmb/decisions.json`, and
optionally scaffolds remediation plan files for the `plan` verb. It never
modifies code and never deletes audit state.

## What the verbs mean

| Verb | Semantics | Effect on next `/cmb:audit` | Effect on next `/cmb:fix` |
|---|---|---|---|
| **plan** | Real issue, too big to fix inline. See `plan_file`. | Reported with 🗺 marker + link; excluded from Top Priorities. | Excluded from inline-fix menu; appears under "Planned (refresh plan only)". |
| **accept-risk** | We know, we're OK with it. Suppress unless severity escalates or `expires_at` passes. | Moved to "Suppressed (accept-risk)" fold at the bottom; out of Top Priorities. | Hidden from the menu. |
| **dismiss** | False positive / not a real issue. | Omitted from the human report entirely; counts note "(N dismissed)". | Hidden from the menu. |

`fix` is **not** a persisted verb — once a finding is fixed it's resolved and
gone. (That's `cmb:fix`'s job.) "Always fix this *kind* of issue without
asking" belongs in a future per-rule policy, not in `.cmb/decisions.json`.

The full file schema is in
`${CLAUDE_PLUGIN_ROOT}/skills/audit/references/decisions-schema.md`.

## Safety valves (so suppression isn't forever)

A decision is **voided for the current audit run** when:

- **Escalation** — the finding's current severity is *worse* than
  `severity_at_decision`. Accepting a `medium` doesn't suppress a future
  `critical` incarnation of the same finding.
- **Expiry** — `accept-risk` decisions support an optional `expires_at`. Past
  that, they re-surface.

Voided decisions are reported by `cmb:audit` with a `🚨 ESCALATED` or
`⏰ EXPIRED` tag. Use `/cmb:triage --review` to re-walk them.

## Invocation forms

```
/cmb:triage                                            # interactive walk of undecided findings
/cmb:triage <id-or-prefix>                             # bring up a single finding by id
/cmb:triage --rule=<slug> <verb> "<justification>"     # bulk: same verb for every finding of this rule
/cmb:triage --severity=critical,high                   # interactive walk, filtered by severity
/cmb:triage --dimension=security,observability         # interactive walk, filtered by dimension
/cmb:triage --status                                   # read-only: print current decisions and counts
/cmb:triage --review                                   # re-walk only escalated/expired decisions
/cmb:triage --relink <old-id> <new-id>                 # carry a decision across a slug rename
```

When the user passes an explicit verb (`--rule=… <verb> "…"`), skip the
interview for that step and go straight to confirmation.

## Workflow

### 1. Load state and bail kindly if there's nothing to triage

Look for `.cmb/audit/` at the root of the repo (the user's cwd). Read
`.cmb/audit/manifest.json` and each `.cmb/audit/<dimension>.json`. The
contract is `${CLAUDE_PLUGIN_ROOT}/skills/audit/references/output-schema.md`.

**If `.cmb/audit/` is absent or empty**, there is nothing to triage. Do not
hunt for problems yourself. Tell the user plainly:

> No audit found — `cmb:triage` works from a `cmb:audit` run, and there's
> no `.cmb/audit/` in this repo yet. Run `/cmb:audit` first, then
> `/cmb:triage`.

Offer to run `/cmb:audit` if they want, but don't do it unasked, then stop.

Then load `.cmb/decisions.json` via the helper (returns empty state on
missing):

```
python "${CLAUDE_PLUGIN_ROOT}/skills/triage/scripts/cmb_triage_store.py" \
    read --root <audited-repo-root>
```

**Staleness check.** If this is a git repo, compare `manifest.commit` to the
current `HEAD`. If they differ, say so — the decisions you're about to make
will be tied to ids derived from the audit-time code, and if the code has
moved the decisions may not match what a re-audit would produce. Recommend a
fresh `/cmb:audit` first; let the user proceed if they want.

### 2. Compute and summarize the triage queue

The queue is **findings without an existing decision**, ordered by severity
(Critical → Low). Apply any `--severity` / `--dimension` filters first. Skip
findings whose id already has a decision unless the user passed `--review`
(in which case load `apply`'s output and queue up only those classified
`escalated` or `expired`).

Before the interview, print a tight summary so the user sees what they're
about to triage: N findings across D dimensions, distribution by severity,
and any decisions that came back as `escalated` / `expired` / `orphan` from
the helper's `apply` mode. Surface orphans by name — they're a hint that the
user should `/cmb:triage --relink` rather than triage from scratch.

### 3. Per finding: decide

For each finding in the queue, show:

- `id`
- severity + dimension
- title
- `file:line`
- evidence (short — what makes this real)
- recommendation (one line — what would fix it)
- the audit's per-dimension section context if it adds anything

Use `AskUserQuestion` with **five** options:

- **fix later** — leave it undecided; it stays in the regular `cmb:fix`
  menu. Records no state.
- **plan it** — record `verb: "plan"` with a justification. Optionally
  scaffold a plan file (see below).
- **accept the risk** — record `verb: "accept-risk"` with a required
  justification. Optionally take an `expires_at`.
- **dismiss (false positive)** — record `verb: "dismiss"` with a required
  justification.
- **skip for now** — move on without writing anything; revisit later.

For `accept-risk` and `dismiss`, the justification is required by the
schema — gather it. For `plan`, justification is optional but encouraged.

### 4. Plan-file scaffolding (only for `plan`)

When the user chooses `plan`, ask whether to scaffold a stub remediation file
at `audit-reports/<dimension>-<rule>-<short-slug>.md`. If yes, write a
template along these lines and record its path in the decision's `plan_file`
field:

```markdown
# Remediation plan — <title>

**Finding id:** `<id>`
**Severity at decision:** <sev>  ·  **Decided:** <date>  ·  **Decided by:** <who>

## The problem
<copy the audit's evidence + a sentence or two of why this matters here>

## Proposed approach
<empty for the user to fill — bullet points, design sketch, dependencies>

## Acceptance
- [ ] Code change(s):
- [ ] Test(s) added:
- [ ] Verified in-app:
- [ ] Audit re-run shows the finding resolved
```

If the user declines scaffolding, still record the `plan` decision — just
without a `plan_file` pointer.

### 5. Persist incrementally

Write the decision to `.cmb/decisions.json` **after every interview step**
via the helper (atomic temp+rename — a crash mid-walk loses at most the
current finding's input, never the file's integrity):

```
echo '<payload-json>' | python "${CLAUDE_PLUGIN_ROOT}/skills/triage/scripts/cmb_triage_store.py" \
    write --root <audited-repo-root>
```

Or build the payload progressively in memory and call `write` once per step;
either is fine — the helper's contract is that each call replaces the file
atomically.

### 6. Bulk form

`/cmb:triage --rule=<slug> <verb> "<justification>"` — list every finding
in the current audit whose `rule` matches the slug, show them, ask for a
single confirmation, then write all the decisions at once. Use this for
patterns like "we know we don't have correlation IDs anywhere yet" without
walking the same justification N times.

### 7. Summarize and hand off

Close with:

- **What was triaged**: counts by verb, dimensions touched.
- **What was skipped or left undecided**: still surfaces in the next `/cmb:fix`
  menu.
- **Where decisions live**: `git diff .cmb/decisions.json` to review the
  exact changes.
- A reminder that `/cmb:audit` will fold these in next run (counts will show
  suppressed / planned), and `/cmb:fix` will filter the menu accordingly.

## What this skill does NOT do

- Does **not** modify code (that's `cmb:fix`).
- Does **not** delete or modify `.cmb/audit/` (that's `cmb:audit`'s only).
- Does **not** silently fuzzy-match decisions across slug drift — the user
  uses `--relink` explicitly. The audit's "orphans" report surfaces the
  candidates.
- Does **not** commit. The user reviews and commits `.cmb/decisions.json` as
  part of their normal flow.
