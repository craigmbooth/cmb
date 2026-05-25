# Report template

Assemble the final report in this shape. Fill the scorecard and Top Priorities
yourself from the per-dimension sections; paste each dimension's section verbatim
from the text the reviewer returned (or from `.audit-scratch/<dimension>.md` if
you used scratch files).

```markdown
# Full Audit — <repo or directory name>

**Date:** YYYY-MM-DD · **Scope:** <path, or "whole repository"> · **Stack:** <languages / frameworks>

## Scorecard

| Dimension | Score | Headline |
|---|---|---|
| Security | N/10 | <one line> |
| Performance | N/10 | <one line> |
| Best practices | N/10 | <one line> |
| Test coverage | N/10 | <one line> |
| Accessibility | N/10 *or* N/A | <one line, or "no frontend code in scope"> |
| Design system | N/10 *or* N/A | <one line, or "no frontend code in scope"> |
| Infrastructure | N/10 *or* N/A | <one line, or "no infrastructure code in scope"> |
| **Overall** | **N/10** | <e.g. "solid, but one critical security issue"> |

<If any dimension is in the 0–2 critical band, add a one-line call-out here so a
healthy-looking average can't bury it.>

## Changes since last audit

<Built from the step-4 diff. On a first run, replace this whole section with a
single line: "First audit — no prior run to compare against.">

**Since <prior date>: <R> fixed · <N> new · <A> newly-assessed · <O> still open.**

- ✅ **Fixed** (<R>): <title> [<severity> · <dimension>], …
- 🆕 **New** (<N>): **[<severity> · <dimension>]** <title> — `file:line`, …  *(regressions: a dimension that ran before now has an issue it didn't)*
- 🔎 **Newly assessed** (<A>): **[<severity> · <dimension>]** <title> — `file:line`, …  *(dimensions not scored last run, e.g. accessibility switching on — not regressions)*
- ⏳ **Still open** (<O>): **[<severity> · <dimension>]** <title> — open since <first_seen>, …

<Lead with any newly-introduced Critical/High under **New** — a real regression
matters more than raw counts. Don't alarm on **Newly assessed**: those issues may
be long-standing, just never scored before.>

## Top priorities

The highest-leverage fixes across the whole audit, most urgent first. Every
Critical and High finding from every dimension, merged and severity-ordered.

1. **[Critical · Security]** <title> — `file:line` — *Fix:* <fix>
2. **[High · Performance]** <title> — `file:line` — *Fix:* <fix>
3. ...

---

<paste Security section>

---

<paste Performance section>

---

<paste Best practices section>

---

<paste Test coverage section>

---

<paste Accessibility section, or a single line: "**Accessibility** — N/A (no frontend code in scope).">

---

<paste Design system section, or a single line: "**Design system** — N/A (no frontend code in scope).">

---

<paste Infrastructure section, or a single line: "**Infrastructure** — N/A (no infrastructure code in scope).">
```

## Overall score

Use the mean of the dimension scores that ran (exclude any N/A dimension), to one
decimal place. The mean is a convenience summary — the per-dimension scores and
the critical-band call-out carry the real signal, so never let a good average
stand in for "there is a critical issue here."
