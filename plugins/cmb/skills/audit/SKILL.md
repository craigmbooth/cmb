---
name: audit
description: >-
  Multi-dimensional codebase audit. Runs security, performance, and
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

# cmb:audit

Audit a codebase across several quality dimensions at once, fan the work out to
parallel sub-agents, and return one **scorecard** (0–10 per dimension) plus a
**severity-prioritized list of improvements** for each dimension.

This is a *reviewer*, not a fixer. It reads, scores, and prioritizes — it does
not modify code. That separation is deliberate: an honest assessment you trust
is more valuable than a pile of half-applied edits, and the prioritized list is
what lets the user (or a follow-up fixer) decide what to tackle first.

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
  can't write files. Its message should end with the numeric score and a one-line
  headline so you can build the scorecard without re-reading the whole section.
  As an *optional* optimization, if file writes are available the reviewer may
  also drop its section in `.audit-scratch/<dimension>.md` to keep large findings
  out of the orchestration transcript — but never depend on that working.

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

### 4. Assemble the report

Collect each reviewer's section — from the text it returned, or from
`.audit-scratch/<dimension>.md` if you used files. Build the report using
`${CLAUDE_PLUGIN_ROOT}/skills/audit/references/report-template.md`. In short:

- A **scorecard table** (dimension · score · one-line headline) with an
  **Overall** score (the mean of the dimension scores; if any dimension scored
  in the 0–2 critical band, say so explicitly next to the overall — a healthy
  average can hide a critical).
- A **cross-cutting Top Priorities** list: merge every Critical and High finding
  from all dimensions into one severity-ordered list. This is the "what do I do
  first" answer across the whole audit.
- The **per-dimension sections** exactly as each reviewer returned them.

Write the report to `audit-reports/cmb-audit-YYYY-MM-DD.md` (create the
directory; use today's date). If a report for today already exists, append a
`-2`, `-3`, … suffix rather than overwriting.

### 5. Summarize in chat

Print the scorecard table, the top 3–5 cross-cutting priorities, and the path to
the full report. Keep it tight — the file has the detail; the chat is the
at-a-glance verdict.

## Adding a dimension

To add a dimension (e.g. test coverage, documentation quality, API design),
create `skills/audit/references/<dimension>.md` in the plugin source, following
the shape of the existing rubrics
(what to look for · severity guidance · scoring bands · section format), then add
it to the dispatch list in step 3 and the scorecard. The orchestration logic
doesn't change — it's already dimension-agnostic.
