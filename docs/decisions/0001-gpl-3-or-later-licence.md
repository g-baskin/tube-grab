# 0001. License under GPL-3.0-or-later with an attribution term

Date: 2026-10-28

## Status

Accepted

## Context

Tube Grab had no license, so nobody else had permission to use it. The owner, AutomationGod, wanted to share it while making sure anyone who reuses it keeps the owner's credit.

## Decision

We decided to license Tube Grab under the GNU GPL, version 3 or any later version. Copyright notices name AutomationGod in `main.py`, `desktop.py`, the README and the app footer. Under section 7(b), the README adds one term: anyone conveying Tube Grab or a modified version must keep those notices and the attribution "Tube Grab © 2026 AutomationGod".

## Consequences

**Positive:**
- Credit has to stay with every shared copy, and modified versions must stay open source under the GPL.

**Negative:**
- Anyone who wants to ship it inside closed-source software is blocked, which may limit adoption.
- Relicensing later needs agreement from every copyright holder, so outside contributions make it harder.

**Neutral:**
- Using the app privately, without sharing copies, carries no extra obligations.

## Alternatives Considered

### Alternative: MIT

Short and permissive, and it requires keeping the copyright notice. Rejected because modified versions could be closed-source.

### Alternative: Apache 2.0

Adds a NOTICE file and a patent grant. Rejected for the same reason as MIT, and because it's heavier than this project needs.

### Alternative: Custom "personal use only, credit required"

Strongest control, but it isn't an open-source license, and many people and tools avoid custom terms.

---

*Linked from:* commit 9bdead8, `LICENSE`, README "License" section
