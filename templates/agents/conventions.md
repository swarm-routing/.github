- An issue has one type label, its area label(s), one `priority:P1|P2|P3`
  (not on epics) and a `release:vX.Y.Z` label only when a release gates it.
  Body: **Context** · **Scope** · **Acceptance criteria** (checkboxes) ·
  **Depends on** · **References**. A child of an epic says "Part of #N" and
  is linked as a sub-issue.
- Comments you post end with the Claude Code footer.
- A generated epic list is never edited by hand: refresh it with
  `swarm-routing/.github` `tools/epics/epics.py`.

Before you file, close or re-scope an issue or an epic, read
[the conventions in full](https://github.com/swarm-routing/.github/blob/main/docs/agents/conventions.md).
