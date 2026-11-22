## Agent skills

The org's procedures ship as the Claude Code plugin **`swarm-routing`**
([`swarm-routing/skills`](https://github.com/swarm-routing/skills)), which this
repository's `.claude/settings.json` enables; other agents install the same
skills with `npx skills add swarm-routing/skills` ([skills.sh](https://skills.sh)).
A skill is the procedure; its script does the work without it (golden rule 9),
so an agent without the skill, or a session that does not read this
repository's settings, starts from the script. Plugin missing (it was
`org-repo` before 2026-11-09)? Run `claude plugin marketplace update
swarm-routing` and start a new session.

| Task | Script (any agent) | Skill |
|------|--------------------|-------|
| Bring this repository onto the org templates, or fix their drift | `swarm-routing/.github` `tools/org-sync/org_sync.py` | `org-repo` |
| Write or review a protocol's paper-fidelity sheet (`docs/fidelity.md`) | `swarm-routing/.github` `tools/fidelity/fidelity.py` | `fidelity-sheet` |
| Check a diff against the org golden rules before a PR or a review | `swarm-routing/.github` `tools/protocol-review/check_invariants.py` | `protocol-review` |
| Bring the README, AGENTS/CLAUDE/CONTEXT and docs/ to the org standard | `swarm-routing/.github` `tools/docs-review/check_docs.py` | `docs-review` |
| Find new papers on a topic, or confirm a reference (free sources only) | `swarm-routing/.github` `tools/lit-search/lit_search.py` | `lit-search` |
| Give a repository its docs/references.bib, or review it (every paper and org release it relies on, confirmed from its record) | `swarm-routing/.github` `tools/fidelity/fidelity.py` (bib), `tools/zenodo/zenodo.py` | `references` |
| Take open pull requests from review to merge (CI, review threads, merge) | `swarm-routing/.github` `tools/pr-status/pr_status.py` | `pr-shepherd` |
| Measure what a session loads from the agent files, or where a finished session's tokens went | `swarm-routing/skills` `tools/token-audit/token_audit.py` | `token-audit` |
| Register a repository for the OpenSSF Best Practices badge, or check its answers | `swarm-routing/.github` `cmd/bestpractices` (Go) | `bestpractices` |
| Check or bump the release a repository builds on (`swarm-core.lock`, `ns3-tools.lock`) | `swarm-routing/.github` `tools/checks/release_lock.py`, `tools/checks/check-swarm-core-pin.py` | `dependency-bump` |
| Cut a release on the maintainer's request, and its aftercare | `swarm-routing/.github` `tools/release/release_check.py`, `tools/zenodo/zenodo.py` | `release` |
| Record a reviewed SonarQube Cloud false positive or accepted finding | `swarm-routing/.github` `tools/sonar-triage/sonar_triage.py` | `sonar-triage` |

A skill only this repository uses lives in its own `.claude/skills/`; one two
repositories need moves to the plugin. Skills that file, cite and extract
papers stay in the maintainer's private library; a public skill may point to
them, never carry their content.
