---
name: north-star-check
description: Use this skill before proposing or starting any new concrete fix, feature, or build task in the GrowthBook RevOps agent. Checks the proposed work against NORTH_STAR.md's phase list and stops to confirm alignment before proceeding. Trigger this especially when a conversation has gone 3+ exchanges deep into narrow technical fixes without reference back to the broader roadmap.
---

# North Star Check

Before proposing or starting any concrete task (a fix, a new primitive, a refactor, a threshold change, anything):

1. Read NORTH_STAR.md at the repo root.
2. State in one line which phase/item the proposed work maps to.
3. If it doesn't map to anything in the phase list, say so explicitly before proposing it - that's a signal to confirm it's actually the priority, not just the next satisfying thing to fix.
4. If the current conversation has had 3+ consecutive exchanges that are narrow and technical (e.g. tuning one threshold, debugging one function) with no reference back to NORTH_STAR.md, stop and surface that explicitly - don't wait to be asked to zoom out.

This skill exists because it's easy to lose the larger architecture goal (primitives over handlers, trustworthy-over-fast) while chasing individual bugs. The check is mechanical and deliberate, not a vibe - it requires actually reading the document and stating the mapping, every time.
