# Vue 3 Optimization Checklist

Use this while verifying scanner leads and when reading the largest components. Each item says what to look for, why it costs something, and what a good fix looks like.

## Contents
1. Reactivity & rendering
2. Code reuse
3. Component size & structure

---

## 1. Reactivity & rendering

### 1.1 Expensive work in the template
**Look for:** `{{ items.filter(...).length }}`, `v-for="x in sortItems(list)"`, `:style="computeStyle(item)"` inside large `v-for`s, method calls that loop or sort.
**Why:** Template expressions and method calls re-run on *every* render of the component, for every row. `computed` caches until its dependencies change.
**Fix:** Move to a `computed`. For per-row derived values, precompute them into the array in one computed (`rowsWithTotals`) rather than calling a function per row per render.
**Not a finding:** Cheap, O(1) formatting (`formatDate(order.date)`, `t('key')`) — caching it adds complexity for no gain.

### 1.2 v-for keys
**Look for:** `:key="index"`, `:key="i"`, missing `:key`, keys that aren't unique (e.g. `:key="item.category"` when categories repeat), `Math.random()` keys.
**Why:** Index keys make Vue patch the wrong DOM nodes when the list is filtered, sorted or spliced — stale input state, broken transitions, and full re-renders of rows. Random keys force a remount on every render.
**Fix:** Use a stable unique id (`item.id`, `item.sku`). If none exists, a composite (`` `${row.month}-${row.sku}` ``) is fine. Add a comment if the composite isn't obvious.

### 1.3 v-if together with v-for
**Look for:** `v-for` and `v-if` on the same element.
**Why:** In Vue 3 `v-if` has higher precedence, so it can't see the loop variable (a bug), and it's evaluated per item.
**Fix:** Filter in a computed, or move `v-if` to a wrapping `<template>`.

### 1.4 Watchers
**Look for:** `deep: true`, `watch` on a whole large object, watchers that set other reactive state that triggers other watchers, `watch` used to derive a value (should be `computed`), `immediate: true` plus an `onMounted` doing the same thing (double fetch).
**Why:** Deep watchers traverse the entire object on every change. Watch-to-derive creates an extra render cycle and can go stale.
**Fix:** Watch a specific getter (`() => filters.value.status`), use `computed` for derived state, consolidate duplicate triggers.

### 1.5 Oversized reactive state
**Look for:** Large API payloads (hundreds+ records) stored in `ref`/`reactive` that are only replaced wholesale, never mutated in place; big static lookup tables made reactive.
**Why:** Vue makes every nested property reactive with proxies — memory and setup cost scale with payload size.
**Fix:** `shallowRef` for data replaced wholesale (`data.value = await api.get()`), `markRaw` or plain constants for static tables. Add a comment explaining why it's shallow, since in-place mutations won't trigger updates.

### 1.6 Unnecessary re-render triggers
**Look for:** Inline object/array/function props on child components inside loops (`:options="{ a: 1 }"`), a parent re-rendering a large static subtree.
**Why:** New object identity each render makes children re-render.
**Fix:** Hoist constants, `v-once` for truly static blocks, `v-memo` for large lists where rows change rarely (only when measured to matter).

### 1.7 Repeated or redundant fetching
**Look for:** The same API call made in several components on mount, data reloaded on every filter change when it doesn't depend on that filter.
**Fix:** Shared composable with cached state, or lift the fetch to a parent and pass data down. Only fetch what the changed filter affects.

---

## 2. Code reuse

### 2.1 Duplicated logic → composable or utility
**Look for:** The same function name defined in several files (scanner lists these), identical `loadData` / loading-error-state boilerplate, copy-pasted formatters, the same filtering/sorting code.
**Decide:**
- Stateful or reactive (uses `ref`, `computed`, `watch`, lifecycle hooks) → **composable** `useX()` in `composables/`.
- Pure function → **utility module** (`utils/format.js`). Don't wrap pure functions in `useX()`.
- Before proposing, diff the copies. If they've drifted (different rounding, different locale), note which behavior is correct — the drift itself may be a bug worth flagging.

### 2.2 Component families → shared base component
**Look for:** Several components with the same name suffix (`*Modal.vue`, `*Card.vue`) sharing template skeleton, props (`isOpen`), emits (`close`), and CSS.
**Why:** Fixes (accessibility, Escape handling, scroll lock, focus trap) have to be made N times and drift.
**Fix:** A base component with slots (`<BaseModal :is-open @close><template #header>…</template>…</BaseModal>`) that owns overlay, close behavior and shared styles. Estimate lines saved and list behavioral differences between the copies that the base must support.

### 2.3 Repeated markup within a component
**Look for:** Several near-identical blocks in one template (KPI cards, stat tiles, table sections) differing only by data.
**Fix:** Drive them from an array + `v-for`, or extract a small presentational child component.

### 2.4 Duplicated styles
**Look for:** The same class (`.badge`, `.card-header`, `.modal-overlay`) defined in many `<style scoped>` blocks with the same rules.
**Fix:** Move to a global stylesheet or the shared base component. Check the rules actually match before proposing.

---

## 3. Component size & structure

### 3.1 Oversized components
**Look for:** Components well over ~500 lines, or with many unrelated sections/computed properties. Size is a signal, not the problem — mixed responsibilities are.
**Fix:** Split along feature seams: each card/section becomes a child that owns its own computed state and receives raw data via props. Name the proposed children and say which computed/methods move into each.

### 3.2 Prop drilling and emit chains
**Look for:** Props passed through components that don't use them; events re-emitted up multiple levels.
**Fix:** `provide`/`inject` for app-wide context, a composable with module-level state, or the project's store if it has one.

### 3.3 Mixed API styles
**Look for:** Options API, `setup()` returning everything, and `<script setup>` mixed across the codebase.
**Only report** if it causes real friction (e.g. composables awkward to use from Options components) or the user asked about consistency. Match whichever style the project's CLAUDE.md or majority of files use.

### 3.4 Registration and imports
**Look for:** Components used in a template but not imported/registered (renders nothing and logs a "Failed to resolve component" warning), imported but unused components.
**Why:** The former is a silent bug; the latter is dead code.
