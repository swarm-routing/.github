## Working defaults

Condensed from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).

- **Assumptions:** state the ones that matter. Ask only when the choice
  belongs to the maintainer: a default, a published number, a cell, the scope.
  Then give your recommendation and its reason with the question, never the
  options alone. Otherwise pick the sensible option, say which, and keep
  going. Long unattended runs, like campaigns, depend on that.
- **Simplicity:** the least code that solves the task. No speculative
  features, configurability or abstractions for one use.
- **Surgical diffs:** every changed line traces to the request. Match the
  surrounding style. Mention unrelated dead code rather than deleting it, and
  remove only the orphans your own change created.
- **Verifiable goals:** a bug gets a reproducing test first; a refactor passes
  before and after. Finish when the check passes, not when the code looks right.

## Session habits

- **Handoffs are always a ticket.** When a session ends with work in flight, or a
  handoff is asked for, open a GitHub issue from the *Handoff* template (label
  `handoff`); a session that continued a handoff updates that issue instead of
  opening another. Never write a handoff file in the repo. A session that
  continues handed-off work starts from the newest open `handoff` issue for
  that work; a new task starts from the request. Close the issue, and any
  older one it superseded, when the work it hands off is done ([AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md) item 5).
- **Attach only the repositories the task needs.** Each attached repository's
  agent files are loaded into every request, whether the task touches it or
  not.
- **Start from the record, not from memory:** the matching `handoff` issue,
  then the issue's acceptance criteria, then `main`. Check a claim against its
  source before it goes into an issue or a PR.
- **Script what repeats.** A check or a lookup run more than a few times
  becomes a script in `tools/` that prints a summary; the model reads the
  verdict, not the raw data (AntHocNet ADR-0014).
- **Automate what can be automated** (org CONTRIBUTING invariant 8): a
  step stays manual only when no API or permission exists for it, or the
  maintainer reserves the decision; list it in swarm-routing/.github#568.
- **Measure before cutting or adding agent text:** the `token-audit` skill
  (`swarm-routing/skills` `tools/token-audit/token_audit.py`) prints what a
  session loads and where a finished session's tokens went.

## Response style — caveman (token economy)

Answer in tight, low-filler prose: drop hedging, pleasantries, and preamble; keep
the substance. Fewer output tokens on every reply, same information.

**Carve-out (the record stays full).** Keep byte-for-byte exact — code,
commands, file paths, error text, benchmark numbers. And keep the *durable
record* detailed, never terse: commit messages, PR bodies, ADRs, `docs/`, and
issue / finding threads. Cross-session traceability depends on those being
complete — AntHocNet's AC_BE_NQOS / A2 investigation was only recoverable
because the issue threads were thorough. Caveman the chat, not the record.

## Agent pitfalls

- **Before every push, run the repository's `make check`** (where it has
  none, the commands of its "Build & verify" section; `make pre-push
  TITLE='…'` where the Makefile has it) **and check the PR title** is a
  lowercase Conventional Commit, `type(scope)!: subject` with the type one
  of `feat fix docs style refactor perf test build ci chore revert` and a
  subject that starts lowercase. A check that goes red because a step was
  skipped costs a whole CI round (swarm-routing/.github#586). Never add
  commits to an unrelated PR to re-apply org-sync or fix template drift:
  each repository is checked at the template commit its
  `.github/org-sync.lock` pins, and org-bot's refresh PR moves the pin and
  the text together.
- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- In an issue, PR or comment, write every issue of another repository in
  full, `swarm-routing/<repo>#N`, also inside a list or a range. A bare `#N`
  links to the repository the text is in: in
  `swarm-routing/AntHocNet#65, #151` the second number points at this
  repository's #151 (swarm-routing/.github#277). An ns-3 item on GitHub is
  its full GitLab URL (or a link whose text is `nsnam/ns-3-dev#N`); in
  anything bound for ns-3's GitLab, an item of ours is its full GitHub URL,
  never `swarm-routing/<repo>#N` or a bare `#N` / `!N` (CONTRIBUTING "ns-3
  bugs (RCAPA)").
- A sentence in `ROADMAP.md` or an AGENTS.md that calls an issue done is not
  evidence: read the issue's acceptance criteria. On 2026-11-12 nine issues
  described as done had open criteria (swarm-routing/.github#274).
- Change text inside `org-sync:begin/end` markers only through the template
  in `swarm-routing/.github` `templates/`: one PR there, then org-bot's
  `bot/org-sync` refresh PR in each repository. A hand edit per repository
  stays red on `check / org-sync` (swarm-routing/.github#236).
- In a repository with a merge queue, merge by enabling auto-merge (squash);
  a direct merge (`PUT pulls/<n>/merge`) is refused with HTTP 405. Only the
  required checks (`gh api 'repos/{owner}/{repo}/rules/branches/main'`, which
  `gh` fills from the checkout) gate a merge: a red or pending report-only
  check (`codecov/patch`, Sonar) is triaged, not waited on. `dco` checks
  outside contributors' PRs only: on a member's, an agent's or the org bot's
  PR it passes at once (swarm-routing/.github#586), and a red `dco` on an
  outside contributor's commit holds the PR until that author signs off.
  `dco` is not a required check and runs on
  `pull_request` only, so merge an outside contributor's PR, by auto-merge or
  directly, only after `dco` passed on the head commit that merges. Never push
  to an outside contributor's PR: ask them for the change, or make it in a
  follow-up PR after the merge (swarm-routing/.github#288). If the maintainer
  must push to such a PR, first disable auto-merge, or, if the PR is already
  in a merge queue, remove it from the queue (disabling auto-merge does not).
  Re-enable auto-merge, or enqueue it again, only after `dco` passed on the
  new head: GitHub keeps auto-merge on after a push by someone with write
  access, and `dco` is not a required check.
- `review / coderabbit` is a required check (the review gate,
  swarm-routing/.github#294): it passes once CodeRabbit has reviewed the PR,
  once it says it will not, for a draft, or 30 minutes after the PR opened
  (then with one comment). So auto-merge may be enabled at once: the merge
  waits for the gate, and the ruleset holds it while a CodeRabbit thread is
  unresolved. Still read every thread and fix or answer it before resolving.
  Where the gate is not required yet (`gh api
  'repos/{owner}/{repo}/rules/branches/main'` does not list it), wait first
  with `python3 -I ../.github/tools/pr-status/pr_status.py gate REPO#N`,
  which waits for CodeRabbit alone (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else: a
  DCO sign-off is a person's own certification (CONTRIBUTING "Outside
  contributions").
- Leave a stale branch (a closed PR's head, a validation branch, a
  superseded bot branch) to org-bot's daily `branch-sweep`, which deletes it
  once its PR has been closed for 2 days, or after 7 days without a commit
  for a `claude/*` or `org-bot/*` branch that never had a PR
  (swarm-routing/.github#595). Agent sessions cannot delete branches; never
  ask the maintainer to delete one.
- Releases are cut on request only: dispatch the release `bump` when the
  maintainer asks, once the version's `release:vX.Y.Z` issues are done and
  its exit criteria in the ladder (`docs/roadmap.md`, or the org ROADMAP's
  release train until it lands) are met; never approve a gated publish. A
  failed publish is recovered with "Re-run all jobs", never "Re-run failed
  jobs" (CONTRIBUTING "Cutting a release"). Never type a release's DOI: read
  it from Zenodo. A public repository's release reaches the site by itself:
  a `[release-sync] <repo> <tag>` issue opens in
  `swarm-routing/swarm-routing.github.io` and a `release-sync.yml` run named
  `Release sync swarm-routing/<repo> <tag>` ends green. If, an hour after
  the release, either is missing, org-bot's hourly `release-sync-watch`
  dispatches that run again within the next hour (swarm-routing/.github#571;
  CONTRIBUTING "Cutting a release"); never dispatch it by hand, and the
  site's weekly Monday run is only the backstop.
- Cite a paper in a public issue, PR or doc by its `https://doi.org/<DOI>`
  link, read from its record (`lit-search` confirms it), or, for a work with
  no DOI, by its publisher's or institution's page; never point into or name
  the private paper library there.
- Never dismiss a security alert, and never rotate or handle a leaked
  secret: both are the maintainer's. Every open alert has a `security`
  ticket kept by the hourly `security-alerts` task (P1 past its SLA), and
  `security-autofix.yml` opens a test-first fix PR for a code finding and a
  proposal for a policy finding (swarm-routing/.github#629); review its PR
  like any other (CONTRIBUTING "Security alerts").
- An ns-3 bug, or an investigation of one, always gets an RCAPA ticket in
  swarm-routing/sim-tools first (form *ns-3 bug (RCAPA)*, labels `rcapa` and
  `ns3-upstream`, ID `NS3-NNN`); its doc in `docs/ns3-rcapa/` and its
  `docs/ns3-bugs.md` row follow, and every workaround links the ID. Upstream
  reports go out only through swarm-routing/ns3-upstream-report (CONTRIBUTING
  "ns-3 bugs (RCAPA)"). A regression in a published library, a version
  another project consumes (a swarm-core or ns3-tools release through its
  lock, PyPI, a vcpkg port), gets an RCAPA too, in that library's repository,
  even when a consumer finds it (a swarm-core lock bump that breaks
  AntHocNet is an `SWC-NNN` in swarm-adapter-ns3, verified with AntHocNet's
  failing check): ticket first (form *Regression in a release (RCAPA)*,
  `<PREFIX>-NNN`), then `docs/rcapa/rcapa-<name>.md` and its row in
  `docs/rcapa/README.md`; the ticket stays open until a release carries the
  fix. A Docker image gets one only when its composition is the cause.
  None for a bug that never reached a published version, for changes in
  .github, the site, skills, benchmarks or ns3-upstream-report, or for a
  typo with no behaviour; the pins and `git tag --contains <commit>` decide,
  never memory (CONTRIBUTING "RCAPA").
