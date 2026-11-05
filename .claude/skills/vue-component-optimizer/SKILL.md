---
name: vue-component-optimizer
description: Analyze Vue 3 component structure and suggest concrete optimizations for rendering performance, reactivity, and code reuse (composables, shared base components, splitting oversized components). Use this whenever the user asks to review, audit, optimize, refactor, or "clean up" Vue components or .vue files, asks why a Vue page is slow or re-renders too much, wants to find duplicated logic across components, asks whether a component is too big, or mentions extracting composables — even if they don't say "optimize". Produces a ranked report with file:line evidence, then offers to apply the fixes.
---

# Vue Component Optimizer

Analyze a Vue 3 codebase (or a subset of it) and produce a prioritized, evidence-backed list of optimizations in three areas:

1. **Reactivity & rendering** — work done on every render that doesn't need to be, unstable list keys, over-broad watchers, oversized reactive state.
2. **Code reuse** — logic, components, and styles duplicated across files that should become a composable, a shared component, or a utility.
3. **Component size & structure** — components doing too many jobs, prop drilling, inconsistent API styles.

The deliverable is a report the user can act on, followed by an offer to apply the fixes they pick. Do not edit code until the user chooses what to apply — a refactor they didn't ask for is expensive to review and easy to get wrong.

## Workflow

### 1. Scope and context

- Figure out the target: a single file, a directory, or the whole app. Default to the directory containing the Vue source (usually `src/` or `client/src/`).
- Read project conventions first if present: `CLAUDE.md` (root and frontend dir), `package.json` (Vue version, router, state library, build tool). Conventions change what counts as a finding — e.g. a project that mandates the Options API shouldn't get "migrate to `<script setup>`" suggestions, and a project rule like "delegate .vue edits to a specific agent" governs how you apply fixes later.

### 2. Run the scanner

```bash
python3 <skill-dir>/scripts/scan_vue.py <target-dir> --format text
```

It prints a deterministic inventory: per-file size and API style, heuristic hotspots (with line numbers), and cross-file duplication candidates (same-named functions, near-identical components, repeated CSS classes). Use `--format json` if you want to post-process.

**Treat scanner output as leads, not findings.** It is regex-based and will produce false positives (e.g. a function called in the template that is cheap and pure is fine; two functions with the same name may do different things). Its job is to tell you where to look so you don't have to read 10,000 lines blind.

### 3. Verify by reading code

For each lead worth pursuing, open the file at the reported lines and confirm:
- Is it actually a problem *here*? (How big is the list? How often does it re-render? Is the function expensive or trivially cheap?)
- What's the concrete fix, and does it preserve behavior?
- For duplication: diff the candidates. Only call it duplication if the logic is genuinely the same or differs by parameters.

Then look beyond the scanner — it can't see design-level issues. Read the largest components and the component families it flags and ask the questions in `references/checklist.md`. Read that file before this step; it explains each pattern, why it matters, and what a good fix looks like.

### 4. Rank

Order findings by **impact ÷ effort**, and be honest about impact. In a small demo app, a `.filter()` in a template over 30 items is a nitpick; in a 5,000-row table it's the headline. Use three tiers:

- **High** — measurable user-facing cost (work scales with data size on every render, large lists re-mounting due to bad keys, watchers triggering cascades) or duplication that is actively causing bugs/inconsistency.
- **Medium** — clear maintainability wins with low risk (extract a composable used in 3+ places, split a 1,000+ line component along an obvious seam).
- **Low** — polish and consistency.

Drop anything you couldn't verify. A short report of real issues beats a long one padded with guesses — the user will stop trusting the list after the first false positive.

### 5. Report

Use this structure:

```markdown
# Vue Component Optimization Report
Scope: <dirs/files> · <N> components scanned · <date>

## Summary
<2-4 sentences: overall health, the top 3 things worth doing, rough effort.>

## Findings

### [High] <short title>
- **Where:** `path/File.vue:123`, `path/Other.vue:45`
- **Problem:** <what happens and why it costs something — be specific>
- **Fix:** <what to change>
  ```vue
  <!-- before -->
  ...
  <!-- after -->
  ...
  ```
- **Effort / risk:** <S/M/L> · <what could break, what to test>

### [Medium] ...

## Reuse opportunities
<Table: proposed composable/component/util → what it replaces → files affected → lines saved (approx).>

## Not worth changing
<Optional: leads you checked and deliberately rejected, one line each, so the user knows they were considered.>
```

Keep before/after snippets minimal — just enough to show the change. Number findings so the user can say "apply 1, 3 and 5".

### 6. Offer to apply

End by asking which findings to apply. When applying:
- Follow project rules for who edits what (e.g. if CLAUDE.md says .vue changes go through a specific subagent, delegate to it with the finding text and file:line references).
- Apply one finding at a time, smallest-risk first, and keep behavior identical unless the finding is a bug fix.
- Verify after changes: run the project's build/lint/tests if available, and if a browser tool is available, load the affected pages and check the console for Vue warnings.
- Add a brief comment where the reason for a change isn't obvious from the code (e.g. why something is `shallowRef`, why a key is composite).

## Calibration notes

- **Prefer computed over methods only when it matters.** Template function calls re-run every render; that's only worth changing if the function is non-trivial (loops, sorting, formatting large lists) or the component re-renders often. Formatting a single date is fine.
- **Composables are for stateful or reactive logic.** Pure helpers (formatCurrency) belong in a plain utility module, not a `useX()` composable.
- **Don't recommend abstractions for two call sites** unless they're already drifting apart. Three or more is the usual threshold.
- **Shared base components** (e.g. a `BaseModal` for six modals) are worth it when the copies share structure *and* behavior (overlay, close-on-escape, focus handling, header/footer slots), not just looks.
- **Splitting large components**: size alone isn't the problem; mixed responsibilities are. Propose splits along data/feature seams (one child per card/section that owns its own computed state), not arbitrary line counts.
- Respect the project's API style. Don't propose an Options → Composition migration as a finding unless the user asks or the mix is causing real problems.
