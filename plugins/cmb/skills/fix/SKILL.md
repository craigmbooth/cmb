---
name: fix
description: >-
  Concurrent Multi-pass Bot (cmb) — apply fixes for the issues that cmb:audit
  found. Reads the audit's machine-readable findings from .cmb/audit/, shows a
  summary, lets the user choose which categories and which specific findings to
  fix, then makes the edits and runs the project's tests. The companion to
  cmb:audit: audit reviews and scores, fix acts on the result. INVOCATION: this
  skill runs ONLY when the user explicitly types the /cmb:fix slash command
  (optionally with a path or category, e.g. `/cmb:fix security`). Do NOT trigger
  it automatically or proactively — phrases like "fix the bugs", "clean this up",
  or "address the issues" should NOT invoke it on their own. Wait for the explicit
  /cmb:fix command; when in doubt, do not invoke.
---

# cmb:fix — Concurrent Multi-pass Bot

Act on the findings from a `cmb:audit` run. The audit is a *reviewer* — it reads,
scores, and records findings to `.cmb/audit/` but never changes code. `cmb:fix` is
the *fixer*: it reads those findings, lets the user decide what to tackle, and
makes the edits.

The separation is deliberate. Fixing is consequential and easy to overdo, so this
skill never fixes everything by default and never guesses at problems — it works
only from what the audit actually recorded, and only on what the user picks. It
**edits the working tree but does not commit** (the user reviews the diff and
commits, or runs their ship flow), and it **does not modify `.cmb/audit/`** — the
audit is the single source of truth for audit state. After fixing, you re-run
`/cmb:audit` to confirm the fixes are real.

## Workflow

### 1. Load the audit state — and bail kindly if there is none

Look for `.cmb/audit/` at the root of the repo (the user's cwd). Read
`.cmb/audit/manifest.json` and each `.cmb/audit/<dimension>.json`. The exact shape
is in `${CLAUDE_PLUGIN_ROOT}/skills/audit/references/output-schema.md` — read it if
you need the field definitions.

Also load `.cmb/decisions.json` if it exists (the per-finding decisions
recorded by [`cmb:triage`](../triage/SKILL.md) — schema at
`${CLAUDE_PLUGIN_ROOT}/skills/audit/references/decisions-schema.md`). Use the
helper to read it and classify decisions against the current findings:

```
python "${CLAUDE_PLUGIN_ROOT}/skills/triage/scripts/cmb_triage_store.py" \
    apply --root <audited-repo-root> --manifest .cmb/audit/manifest.json
```

The `applied` array tells you which findings are `suppressed` (accept-risk),
`planned`, `dismissed`, `escalated`, or `expired`. You'll use this in step 2
to filter the menu and in step 4 to short-circuit the interview.

**If `.cmb/audit/` is absent or empty**, there is nothing to fix *from*. Do not
start hunting for problems yourself and do not fabricate findings — that's the
audit's job, and inventing work here defeats the point of the two-skill split.
Instead, tell the user plainly:

> No audit found — `cmb:fix` works from a `cmb:audit` run, and there's no
> `.cmb/audit/` in this repo yet. Run `/cmb:audit` first, then `/cmb:fix`.

Offer to run `/cmb:audit` now (by following the audit skill) if they'd like, but
don't do it unasked. Then stop.

**Staleness check.** If this is a git repo, compare `manifest.commit` to the
current `HEAD` short SHA. If they differ — or `manifest.generated_at` is clearly
old — the code has moved since the audit, so line numbers and even whole findings
may be out of date. Say so, and recommend re-running `/cmb:audit` for an accurate
picture. "Clearly old" is a judgment call, and when there's no git (or no commit
recorded) to corroborate, don't agonize over it or block on it — step 5 re-reads
each file before touching it, so a stale map is caught at the moment it matters.
You can always proceed; the user just deserves a heads-up when the map may not
match the territory.

### 2. Summarize the problems

Print a tight summary so the user can decide where to spend effort:

- The **scorecard** from the manifest (dimension · score · headline · overall).
- Per dimension, the **finding counts** by severity.
- The **findings themselves**, grouped by dimension and ordered by severity, each
  as: `[severity] title — file:line` plus its one-line recommendation.

**Apply decisions to the menu.** Use the `applied` payload from step 1:

- `dismissed` and `suppressed` (accept-risk) findings: **omit** from the menu
  entirely. Mention them at the bottom in one line ("N suppressed by
  accept-risk, M dismissed — see `.cmb/decisions.json`").
- `planned` findings: list them in a separate "Planned (refresh plan only,
  not for inline fix)" bucket, each with `→ <plan_file>` if recorded.
- `escalated` / `expired` findings: list normally in the menu with a 🚨 or
  ⏰ marker — the safety valve voided the decision and they're back in play.
  Mention this explicitly: "(2 findings are back in play: an accept-risk
  escalated and an expiry hit; run `/cmb:triage --review` to re-decide.)"

Keep it scannable — this is a menu, not the full report. Point the user to
`audit-reports/` for the prose if they want depth.

### 3. Let the user choose categories

**First, honor any choice already in the invocation.** If the user already named
what they want — `/cmb:fix security`, "fix all the security issues", "just the
criticals" — treat that as their answer and skip the question it resolves. Asking
people to re-confirm a decision they just stated is annoying; the interview exists
to *gather* missing choices, not to gate ones already made. Only fall back to
asking when the scope is genuinely unspecified.

Otherwise, ask which **categories (dimensions)** they want to fix. Offer only
dimensions that actually have findings — fixing a clean dimension is meaningless.

Use `AskUserQuestion` (multi-select) when the categories fit (it allows up to four
options per question); if more than four dimensions have findings, present them as
a short numbered list and ask the user to reply with the ones to fix (or "all").
Let "all" be an easy choice.

### 4. Interview within each chosen category

For each selected category, show its findings (numbered, with severity,
`file:line`, and the recommendation) and ask **which specific findings** to fix —
again multi-select, or numbered prose if there are many. The user may want only
the criticals, or to skip one they disagree with. Respect that; this interview is
the whole safety mechanism.

While interviewing, flag findings that **aren't a quick mechanical edit** — things
like "no test suite", "add rate limiting", or an architectural change. These are
real, but they're projects, not one-liners. For each one, offer the user an
explicit choice via `AskUserQuestion`:

1. **Implement now (inline)** — proceed with the fix as a normal step-5 edit,
   knowing it may sprawl. Use when scope is genuinely small or the user
   confirms they want it tackled.
2. **Defer with a plan** — record a `plan` decision in `.cmb/decisions.json`
   (so the next audit shows it 🗺 and `cmb:fix` skips it). Optionally scaffold
   a stub plan file at `audit-reports/<dimension>-<rule>-<short>.md` for the
   user to fill in. Write the decision via:

   ```
   echo '<payload-json>' | python "${CLAUDE_PLUGIN_ROOT}/skills/triage/scripts/cmb_triage_store.py" \
       write --root <audited-repo-root>
   ```

   (the helper merges with any existing decisions). **Never** do this without
   an explicit user prompt — the writer must be a deliberate choice, not an
   inferred one.
3. **Skip this round** — no decision recorded; the finding stays in the menu
   on subsequent runs.

This formalizes the "this is a project, not a one-liner" conversation.
Confirm before sprawl, and don't silently turn a "fix" into a refactor.

### 5. Apply the fixes

Work category by category through the selected findings. For each one:

- **Re-read the actual code first.** Treat `file:line` as a hint, not gospel — the
  audit may be stale, code moves. Open the file, find the real issue, and confirm
  it's still there. If on reading it's already fixed or clearly absent, say so and
  skip it rather than forcing an edit to match a stale finding.
- **Apply the smallest fix that genuinely resolves the issue**, guided by the
  finding's `recommendation` and the surrounding code's idioms. Match the
  project's style. Don't opportunistically rewrite nearby code — scope creep in a
  fixer erodes the user's ability to review.
- Prefer the root cause over a band-aid (parameterize the query; don't just escape
  one input), but stay within the finding's intent.

It's normal to leave another category's finding sitting in code you're actively
editing — e.g. fixing a command-injection inside a `try` whose bare `except` is a
flagged best-practices issue the user didn't select. Leave it; honoring the user's
scope beats tidiness, and they'll see it again on the next audit. Resisting that
itch is the feature, not a gap.

Keep edits focused and reviewable — the user hasn't committed yet and will read
the diff.

### 6. Verify

After the edits, **run the project's checks** so a fix that breaks something is
caught now, not later. Detect what the project uses and run the cheap, relevant
ones — e.g. `pytest` / `python -m pytest`, `npm test` / `npm run typecheck`,
`go test ./...`, `cargo test`, `ruff`/`mypy`, a `Makefile` target. Prefer scoping
to the touched area when that's easy. If the project configures no checks of its
own, a syntax/compile check (e.g. `python -m py_compile`) or an available linter
run on just the files you touched is a fine minimal sanity pass — just say that's
what you did. Report pass/fail honestly; if something broke, surface the failure
and offer to revisit the fix rather than leaving it broken. If you can't find any
check to run (or there's no shell), say so plainly — don't claim verification you
didn't do.

### 7. Summarize and hand off

Close with:

- **What was fixed**, grouped by category, each with the file(s) touched.
- **What was skipped or deferred** (user-declined, already-fixed-on-read, or large
  items left as a plan) and why. If you wrote any `plan` decisions to
  `.cmb/decisions.json` via the mid-fix defer path (step 4), name them
  explicitly and link to any scaffolded plan files — the user should see those
  in the diff (`git diff .cmb/decisions.json`).
- **What was hidden by existing decisions** — one line: "N findings skipped
  because of accept-risk / dismiss decisions in `.cmb/decisions.json`." Keep
  the user aware that the menu was filtered.
- The **verification result**.
- A reminder that `cmb:fix` **did not commit** and **did not change `.cmb/audit/`**
  — the user should review the diff and commit (or run their ship flow), then run
  **`/cmb:audit`** to confirm: the audit's diff will show the fixed findings as
  *resolved*, which is the real proof the loop worked.
