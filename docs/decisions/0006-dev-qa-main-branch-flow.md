# 0006. Promote changes through dev → qa → main

Date: 2026-10-28

## Status

Accepted

## Context

Changes had gone straight to `main`. The owner wanted a place to collect and test work before it reaches the main branch.

## Decision

We decided to add `dev` and `qa` branches. Feature work happens on `feature/<slug>` branches and merges into `dev` by pull request. `dev` is promoted to `qa` for testing, and `qa` to `main`. All three started at commit 9bdead8.

`dev`, `qa` and `main` are permanent and must never be deleted (the owner's rule). GitHub rulesets enforce this. "Protect main and qa" requires a pull request and blocks force-pushes and deletion on `main` and `qa`. "Keep dev" blocks deleting `dev`, and pushes to `dev` stay allowed.

## Consequences

**Positive:**
- `main` only gets changes that passed through `dev` and `qa`.

**Negative:**
- Every change takes extra merges to reach `main`, and the branches can drift apart if promotion is skipped.
- There's no CI or test suite yet, so "testing on qa" is manual.

- The repo has "Automatically delete head branches" turned on, so merging the `dev` → `qa` pull request tries to delete `dev`. On 2026-10-28 this deleted `dev` once; it was restored at the same commit, and the "Keep dev" ruleset added. Without that ruleset, every promotion would delete `dev`.

**Neutral:**
- New pull requests should target `dev`, not `main`.
- Promotions to `qa` and `main` go through pull requests. GitHub rejects direct pushes to them.

## Alternatives Considered

### Alternative: Trunk-based (everything into main)

Fewer steps, but no staging area, which is what the owner asked for.

### Alternative: dev → main only

One step shorter. Rejected in favour of a separate qa stage.

---

*Linked from:* PR #1 and PR #2 (both target `dev`)
