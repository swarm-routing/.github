## Working defaults

Condensed from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).

- **Assumptions:** state the ones that matter. Ask only when the choice
  belongs to the maintainer (a default, a published number, a cell, the
  scope), with your recommendation and its reason, never the options alone.
  Otherwise pick the sensible option, say which, and keep going: long
  unattended runs, like campaigns, depend on that.
- **Simplicity:** the least code that solves the task. No speculative
  features, configurability or abstractions for one use.
- **Surgical diffs:** every changed line traces to the request. Match the
  surrounding style. Mention unrelated dead code rather than deleting it, and
  remove only the orphans your own change created. Update the doc or ADR of a
  documented decision you change.
- **Verifiable goals:** a bug gets a reproducing test first; a refactor passes
  before and after. Finish when the check passes, not when the code looks right.

## Session habits

- **Handoffs are always a ticket**: work in flight at a session's end, or a
  handoff asked for, is an issue from the *Handoff* template (label
  `handoff`), never a file in the repo; a session continuing a handoff
  updates that issue. Continued work starts from the newest open `handoff`
  issue for it, a new task from the request; close the issue, and any older
  one it superseded, when its work is done ([AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md) item 5).
- **Attach only the repositories the task needs**: every request loads each
  attached repository's agent files.
- **Start from the record, not from memory:** the matching `handoff` issue,
  then the issue's acceptance criteria, then `main`. Check a claim against its
  source before it goes into an issue or a PR.
- **Script what repeats**: a check or lookup run more than a few times
  becomes a script in `tools/` that prints a summary; read the verdict, not
  the raw data (AntHocNet ADR-0014).
- **Automate what can be automated** (org CONTRIBUTING invariant 8): a step
  stays manual only when no API or permission exists for it, or the
  maintainer reserves the decision; list it in swarm-routing/.github#568.
- **Measure before cutting or adding agent text** with the `token-audit`
  skill (`swarm-routing/skills` `tools/token-audit/token_audit.py`). MCP
  servers, plugins, token habits and the long form of each pitfall below:
  [`docs/agents.md`](https://github.com/swarm-routing/.github/blob/main/docs/agents.md)
  in swarm-routing/.github (ADR-0005).

## Response style — caveman (token economy)

Answer in tight, low-filler prose: no hedging, pleasantries or preamble; same
information, fewer output tokens. **The record stays full:** code, commands,
paths, error text and benchmark numbers byte-for-byte, and commit messages,
PR bodies, ADRs, `docs/` and issue threads detailed (AntHocNet's AC_BE_NQOS /
A2 investigation was recoverable only from thorough threads). Caveman the
chat, not the record.

## Agent pitfalls

- **Before every push, run `make check`** (none: the "Build & verify"
  commands; `make pre-push TITLE='…'` where it exists) **and check the PR
  title** (Git workflow): a skipped step costs a CI round
  (swarm-routing/.github#586).
- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- Edit files with the editor tools, never a shell heredoc or `sed -i`, and
  touch one repository per command (swarm-routing/.github#578).
- Stage files by name, never `git add -A`; keep build output in `.gitignore`
  (swarm-routing/.github#644).
- A Go test reads only files under `cmd/` or `internal/` (`testdata/`)
  (swarm-routing/.github#587).
- Clean up only your own directory, never a shared one
  (swarm-routing/.github#644).
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- Write another repository's issue in full, `swarm-routing/<repo>#N`, also in
  a list or range: a bare `#N` links to the repository the text is in
  (swarm-routing/.github#277). An ns-3 item is its GitLab URL (or link text
  `nsnam/ns-3-dev#N`); text bound for ns-3's GitLab names ours by full GitHub
  URL (CONTRIBUTING "ns-3 bugs (RCAPA)").
- An issue called done in `ROADMAP.md` or an AGENTS.md is not evidence: read
  its acceptance criteria (swarm-routing/.github#274).
- Change text inside `org-sync:begin/end` markers only through
  `swarm-routing/.github` `templates/`, then org-bot's refresh PRs; never add
  such commits to an unrelated PR (swarm-routing/.github#236).
- With a merge queue, merge by enabling auto-merge (squash); a direct merge is
  refused (HTTP 405). Only the required checks (`gh api
  'repos/{owner}/{repo}/rules/branches/main'`) gate a merge; a report-only
  check (`codecov/patch`, Sonar) is triaged, not waited on. Merge an outside
  contributor's PR only after `dco` passed on its head, and never push to it
  (swarm-routing/.github#288; CONTRIBUTING "Merge when CI is green").
- `review / coderabbit` is required (swarm-routing/.github#294), so
  auto-merge may be enabled at once; still fix or answer every CodeRabbit
  thread before resolving it, and call a PR thread-free only after
  `pulls/N/comments` and the reviews show none. Where the gate is not
  required yet, wait with `pr_status.py gate REPO#N`
  (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else
  (CONTRIBUTING "Outside contributions").
- Never delete a stale branch or ask the maintainer to: org-bot's daily
  `branch-sweep` does (swarm-routing/.github#595).
- Releases are cut on request only, once the version's `release:vX.Y.Z`
  issues and its ladder exit criteria are done; never approve a gated publish;
  recover a failed publish with "Re-run all jobs"; read a DOI from Zenodo,
  never type it; never dispatch the site's `release-sync.yml` by hand
  (swarm-routing/.github#571; CONTRIBUTING "Cutting a release").
- Cite a paper by its `https://doi.org/<DOI>` link, read from its record
  (`lit-search`), or a DOI-less work by its publisher's page; never point into
  or name the private paper library.
- Never dismiss a security alert or handle a leaked secret: both are the
  maintainer's; review `security-autofix.yml`'s PRs like any other
  (swarm-routing/.github#629; CONTRIBUTING "Security alerts").
- An ns-3 bug, or its investigation, gets an RCAPA ticket in
  swarm-routing/sim-tools first (`NS3-NNN`), then its doc and register row;
  every workaround links the ID, and upstream reports go out only through
  swarm-routing/ns3-upstream-report. A regression in a published library
  version gets one in that library's repository (`<PREFIX>-NNN`), open until a
  release carries the fix; the pins and `git tag --contains` decide, never
  memory (CONTRIBUTING "RCAPA", "ns-3 bugs (RCAPA)").
