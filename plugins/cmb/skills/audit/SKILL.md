---
name: audit
description: >-
  Concurrent Multi-pass Bot (cmb) — a multi-dimensional codebase audit. Runs
  security, performance, and
  language-specific best-practices reviewers in parallel (plus accessibility when
  frontend/UI code is present), then produces a 0–10 scorecard per dimension and a
  severity-prioritized list of improvements, saved as a dated markdown report and
  summarized in chat. INVOCATION: this skill runs ONLY when the user explicitly
  types the /cmb:audit slash command (optionally with a path, e.g. `/cmb:audit
  services/billing`). Do NOT trigger it automatically or proactively — phrases
  like "review the code", "audit this", or "how's the code quality" should NOT
  invoke it on their own. Wait for the explicit /cmb:audit command; when in doubt,
  do not invoke.
---

# cmb:audit — Concurrent Multi-pass Bot

Audit a codebase across several quality dimensions at once, fan the work out to
parallel sub-agents, and return one **scorecard** (0–10 per dimension) plus a
**severity-prioritized list of improvements** for each dimension.

This is a *reviewer*, not a fixer. It reads, scores, and prioritizes — it does
not modify code. That separation is deliberate: an honest assessment you trust
is more valuable than a pile of half-applied edits, and the prioritized list is
what lets the user (or a follow-up fixer) decide what to tackle first.

Each run produces two things: a dated human **markdown report** under
`audit-reports/`, and a machine-readable **`.cmb-audit/`** state directory the
*next* run reads to tell you what's been **fixed, what's new, and what's still
open** since last time. The dimensions are unchanged; the findings just also get
written in a stable JSON format (see step 4 and `references/output-schema.md`).

## The dimensions

Four core dimensions always run. Accessibility and Design system run only when
there's frontend/UI code in scope; Infrastructure runs only when there's
infrastructure-as-code (Terraform, Docker, CI/CD) in scope. Scoring a conditional
dimension on a codebase that lacks it is noise, not signal.

| Dimension | Always? | What it judges |
|---|---|---|
| **Security** | yes | Vulnerabilities, unsafe input handling, authn/authz, secrets, dependency risk |
| **Performance** | yes | Algorithmic cost, DB query patterns (N+1), caching, I/O, resource leaks |
| **Best practices** | yes | Language/framework idioms, structure, error handling, maintainability |
| **Test coverage** | yes | Stakes-weighted coverage: are critical & error paths tested, are the tests meaningful |
| **Accessibility** | only if frontend detected | WCAG issues: semantics, alt text, contrast, keyboard nav, ARIA, focus |
| **Design system** | only if frontend detected | CSS/styling: is there a design system; are tokens/CSS variables used; are colors & sizes hardcoded in markup |
| **Infrastructure** | only if IaC detected | Terraform/Docker/CI misconfig: exposed resources, secrets, encryption, root containers, least-privilege |

The dimension list is extensible — see "Adding a dimension" at the end.

## Workflow

### 1. Resolve scope

If the user passed a path (e.g. `/cmb:audit services/billing`), audit that
path. Otherwise audit the whole repository from its root.

Build a file inventory for the scope using whatever tools are available — don't
assume a shell exists. `git ls-files <scope>` (respects `.gitignore`) or `find`
when you have a shell; the Glob tool (e.g. `<scope>/**`) when you don't. Note the
rough size — it changes how reviewers should sample (see step 3).

### 2. Profile the codebase

Spend a moment understanding what you're auditing before dispatching. Determine:

- **Languages present** — from file extensions and manifests (`pyproject.toml`,
  `package.json`, `go.mod`, `Cargo.toml`, `pom.xml`, `Gemfile`, …).
- **Frameworks** — e.g. FastAPI/Django/Flask, React/Vue/Svelte, Rails, Spring.
  Reviewers need this so "best practices" means the *right* idioms.
- **Frontend/UI present?** This decides whether accessibility *and* design-system
  run. Signals: `.html`/`.jsx`/`.tsx`/`.vue`/`.svelte` files, `.css`/`.scss`/
  `.less` files, `templates/` or `static/` directories, or a frontend framework in
  `package.json`. If none of these appear in scope, skip both accessibility and
  design-system and record each as `N/A (no frontend code in scope)` in the
  report.
- **Infrastructure-as-code present?** This decides whether Infrastructure runs.
  Signals: `.tf`/`.tfvars` files, `Dockerfile`/`docker-compose.yml`,
  Kubernetes/Helm manifests, or CI/CD config (`.github/workflows/`, etc.). If none
  appear in scope, skip Infrastructure and record it as `N/A (no infrastructure
  code in scope)`.

Assemble the final dimension list from this profile.

### 3. Dispatch parallel reviewers

This is the core of the skill. **Launch one sub-agent per applicable dimension,
all in a single message, so they run concurrently.** Parallelism is the whole
point — a four-dimension audit should take about as long as the slowest single
dimension, not four times as long.

Give each reviewer sub-agent a prompt containing:

- **Scope**: the repo root and the path(s) to review, plus the file inventory or
  how to get it.
- **Stack**: the languages and frameworks you detected (so judgments are
  idiomatic).
- **Its rubric**: tell it to read
  `${CLAUDE_PLUGIN_ROOT}/skills/audit/references/<dimension>.md` and
  follow it. Each rubric defines what to look for, how to assign severity, the
  scoring bands, and the exact section format to return.
- **The shared rules below** (grounding + scoring), restated so the sub-agent
  doesn't have to infer them.
- **How it returns its section**: have each reviewer **return its full section as
  text in its final message** — that channel always works, even when a sub-agent
  can't write files. Immediately after the prose section, have it return a fenced
  ` ```json ` block of its findings in the per-dimension shape from
  `${CLAUDE_PLUGIN_ROOT}/skills/audit/references/output-schema.md` — each finding
  carrying `severity`, `rule` (a short stable kebab-case slug for the *kind* of
  issue, e.g. `sql-injection`), `title`, `file`, `line`, `evidence`,
  `recommendation`, and a `locator` only when two same-`rule` findings share a
  file. That structured block is what step 4 persists, so it must cover the same
  findings as the prose. Its message should end with the numeric score and a
  one-line headline so you can build the scorecard without re-reading the whole
  section. As an *optional* optimization, if file writes are available the reviewer
  may also drop its section in `.audit-scratch/<dimension>.md` to keep large
  findings out of the orchestration transcript — but never depend on that working.

If you use `.audit-scratch/`, create it first and clean it up afterward (or leave
a single `.gitignore` with `*`); it's a working directory, not a deliverable. If
reviewers return their sections as text, you don't need it at all.

> **If you cannot spawn sub-agents** in the current environment (e.g. you are
> already running as a sub-agent and nesting is unavailable), don't abandon the
> audit — run each dimension yourself, one at a time, using the same rubrics and
> rules. The output format is identical; only the concurrency is lost. Likewise,
> if a tool you reach for is denied (no shell, no file writes), adapt rather than
> stop: read code with Glob/Grep/Read and return results as text. An audit that
> ran sequentially still beats no audit.

#### Shared rule — ground every finding in real code

The fastest way to make this audit worthless is to report plausible-sounding
issues that aren't actually in the code. Every finding **must** cite a concrete
`file:line` (or `file` for whole-file issues) that the reviewer actually opened
and read. No evidence, no finding. It is far better to report five real issues
than fifteen where ten are guesses — a user who catches one hallucinated finding
stops trusting the whole report.

On a large codebase you cannot read everything. Reviewers should **hunt for the
places their dimension lives** rather than reading top-to-bottom: use search to
locate the relevant surfaces (for security: input handling, auth, raw SQL,
`subprocess`/`eval`, secrets; for performance: loops over queries, missing
indexes, unbounded reads; for accessibility: templates and components; for design
system: CSS/SCSS files, `:root`/token definitions, and inline `style=` / hardcoded
hex/px in markup; for test coverage: the `tests/` tree mapped against the
high-stakes modules; for infrastructure: `.tf` files, Dockerfiles, and CI configs),
then read those closely. Breadth of search, depth of reading where it matters.

#### Shared rule — score honestly and comparably

Each dimension returns a 0–10 score. The score reflects the **severity of the
worst problems**, not the raw count of findings, because the point of the number
is to communicate risk at a glance:

- **9–10** — Exemplary. No significant issues; follows best practices throughout.
- **7–8** — Solid. Only minor/low issues; nothing high-severity.
- **5–6** — Needs work. Several medium issues, or one high-severity issue.
- **3–4** — At risk. Multiple high-severity issues, or one critical.
- **0–2** — Critical. One or more critical issues (exploitable vuln, data-loss
  risk, etc.).

A single critical issue caps the score in the 0–2 band even if everything else
is clean — a door left unlocked isn't offset by good landscaping. Findings
within each dimension are ranked by severity:

- **Critical** — exploitable, data-loss, or outage-level. Fix immediately.
- **High** — serious risk or significant degradation. Fix soon.
- **Medium** — meaningful but bounded. Should fix.
- **Low** — minor, stylistic, or nice-to-have.

**Active problem vs missing hardening.** Reserve Critical/High for things that
are *actively* wrong or exploitable in the code as written — an injection, a
swallowed error around a critical write, an O(n²) on a hot path, a control unusable
by keyboard. The mere *absence* of a defense-in-depth measure — security headers,
rate limiting, a test suite, a `<main>` landmark, pagination on a small dataset —
is usually Low or Medium unless you can point to concrete evidence it's
exploitable or already causing harm. This keeps clean, modest code from being
scored as if it were broken, and stops "things you could add" from masquerading
as "things that are wrong." When you catch yourself flagging an absence, ask: is
this code *broken*, or merely *not gold-plated*? Score accordingly.

### 4. Persist findings to `.cmb-audit/` and diff against the prior run

Before writing the human report, persist the findings as JSON under `.cmb-audit/`
at the **root of the audited repo** (the user's cwd — *not* the plugin). This is
what lets the next run, or any other tool, see what changed. The full contract is
`${CLAUDE_PLUGIN_ROOT}/skills/audit/references/output-schema.md`; in short:

- `.cmb-audit/manifest.json` — scorecard, scope, stack, commit, run metadata.
- `.cmb-audit/<dimension>.json` — the findings for each dimension that ran.

**Happy path (shell + Python available).** Assemble the reviewers' JSON findings
blocks into one payload (shape in the schema doc) and pipe it to the helper, which
computes the stable finding ids, reads any prior `.cmb-audit/`, overwrites the
files, and prints the diff:

```
python "${CLAUDE_PLUGIN_ROOT}/skills/audit/scripts/cmb_audit_store.py" \
    write --root <audited-repo-root> < payload.json
```

Capture the printed diff JSON — it classifies findings as **resolved** (present
last run, gone now), **new** (absent last run), and **open** (carried over, with
the original `first_seen`). You surface it in steps 5 and 6.

**Fallback (no shell / no Python).** Write the same files by hand following
output-schema.md: compute each finding's `id` with the documented sha256 rule,
read the prior `.cmb-audit/` yourself, and classify resolved/new/open the same
way. The id rule must match exactly — that's what makes the same issue match
across runs. If even file writes are unavailable, skip persistence and say so in
the summary rather than failing the audit.

**gitignore.** `.cmb-audit/` is tool state, not a deliverable — keep it out of
git. If the audited repo has a `.gitignore` without a `.cmb-audit/` entry, add
one; if there's no `.gitignore`, just mention it rather than creating noise.

### 5. Assemble the report

Collect each reviewer's section — from the text it returned, or from
`.audit-scratch/<dimension>.md` if you used files. Build the report using
`${CLAUDE_PLUGIN_ROOT}/skills/audit/references/report-template.md`. In short:

- A **scorecard table** (dimension · score · one-line headline) with an
  **Overall** score (the mean of the dimension scores; if any dimension scored
  in the 0–2 critical band, say so explicitly next to the overall — a healthy
  average can hide a critical).
- A **Changes since last audit** section built from the step-4 diff: the
  resolved / new / newly-assessed / still-open counts, the resolved wins called
  out by name, and any newly-introduced Critical/High highlighted. Keep **new**
  (a regression in a dimension that ran before) separate from **newly_assessed**
  (a dimension that simply wasn't scored last time, e.g. accessibility switching
  on) — conflating them turns "we added a dimension" into a false alarm. On a
  first run (no prior `.cmb-audit/`), state "first audit — no prior run to
  compare against."
- A **cross-cutting Top Priorities** list: merge every Critical and High finding
  from all dimensions into one severity-ordered list. This is the "what do I do
  first" answer across the whole audit.
- The **per-dimension sections** exactly as each reviewer returned them.

Write the report to `audit-reports/cmb-audit-YYYY-MM-DD.md` (create the
directory; use today's date). If a report for today already exists, append a
`-2`, `-3`, … suffix rather than overwriting.

### 6. Summarize in chat

Print the scorecard table, a one-line **changes-since-last-audit** verdict (e.g.
"2 fixed, 1 new regression, 5 newly-assessed, 3 still open since 2026-05-01" — or
"first audit" when there's no prior run), the top 3–5 cross-cutting priorities,
and the path to the full report. Keep it tight — the file has the detail; the
chat is the at-a-glance verdict. Close by noting the user can run **`/cmb:fix`**
to act on these findings (it reads the `.cmb-audit/` you just wrote).

## Adding a dimension

To add a dimension (e.g. test coverage, documentation quality, API design),
create `skills/audit/references/<dimension>.md` in the plugin source, following
the shape of the existing rubrics
(what to look for · severity guidance · scoring bands · section format), then add
it to the dispatch list in step 3 and the scorecard. The orchestration logic
doesn't change — it's already dimension-agnostic.
