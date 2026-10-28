# 0006. Promote changes through dev → qa → main

Date: 2026-10-28

## Status

Accepted

## Context

Changes had gone straight to `main`. The owner wanted a place to collect and test work before it reaches the main branch.

## Decision

We decided to add `dev` and `qa` branches. Feature work happens on `feature/<slug>` branches and merges into `dev` by pull request. `dev` is promoted to `qa` for testing, and `qa` to `main`. All three started at commit 9bdead8.

## Consequences

**Positive:**
- `main` only gets changes that passed through `dev` and `qa`.

**Negative:**
- Every change takes extra merges to reach `main`, and the branches can drift apart if promotion is skipped.
- There's no CI or test suite yet, so "testing on qa" is manual.

**Neutral:**
- New pull requests should target `dev`, not `main`.

## Alternatives Considered

### Alternative: Trunk-based (everything into main)

Fewer steps, but no staging area, which is what the owner asked for.

### Alternative: dev → main only

One step shorter. Rejected in favour of a separate qa stage.

---

*Linked from:* PR #1 and PR #2 (both target `dev`)
