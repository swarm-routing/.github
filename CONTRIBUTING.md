# Contributing to swarm-routing

Org-wide defaults. A repository's own `CONTRIBUTING.md` overrides this file.
Participation follows the org's default [Code of Conduct](CODE_OF_CONDUCT.md);
where to ask is in the org's default [SUPPORT.md](SUPPORT.md). A repository's
own `CODE_OF_CONDUCT.md` or `SUPPORT.md`, where it has one, takes precedence.
These conventions come from [`swarm-routing/AntHocNet`](https://github.com/swarm-routing/AntHocNet),
the source repository the org was split out of; its
[ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)
is the long form.

## Invariants (every repo)

1. **Licensing per directory, as AntHocNet** ([LICENSING.md](https://github.com/swarm-routing/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)).
   A simulator-free `core/` and the standalone tooling (`tools/`, Python CLIs,
   CI and image scripts) are `MIT OR GPL-2.0-only`; ns-3 modules, the site,
   docs and data are `GPL-2.0-only`. Each repo carries `LICENSE` (GPL-2.0),
   `LICENSE-MIT` and a `LICENSING.md` map. Every original `.h`, `.hpp`, `.cc`,
   `.cpp`, `.py`, `.sh` starts with
   ```cpp
   // Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
   // SPDX-License-Identifier: MIT OR GPL-2.0-only   (or GPL-2.0-only)
   ```
   (`#` comments for Python and shell). An outside contributor may add their
   own `Copyright (c) <year> <Name>` line beneath the org line, never in its
   place, and signs off every commit ([Outside contributions](#outside-contributions)).
   The dependency goes one way: GPL code
   may use the dual parts, never the reverse — a `core/` file includes only the
   C++ standard library, other `core/` files and the dual-licensed core of a
   declared dependency (a protocol's `core/` on swarm-core's `core/`, the
   `core-deps` input of every workflow that runs the licence check: one calling
   `reusable-licence-check.yml`, or one calling `reusable-ns3-ci.yml`, which
   forwards it; file names differ per repo, and each names the same pin). CI
   (`reusable-licence-check.yml`, `tools/checks/check-headers.py`) enforces all
   of it. Where a protocol's `core/` pins swarm-core, the `swarm-core / pin`
   check (`reusable-swarm-core-pin.yml`, `tools/checks/check-swarm-core-pin.py`)
   fails unless `core/CMakeLists.txt`'s `SWARM_CORE_REF`, the `Makefile` and
   every workflow's swarm-core `core-deps` name one commit (the ns-3 build's
   swarm-core dependency: `main` or that commit), and unless swarm-core
   `main`'s `core/` is that commit's `core/`; it checks nothing else about
   the pin. So every merged change to swarm-core's `core/` turns that check
   red on each protocol's `main` and blocks its open PRs: whoever merges it
   opens the pin-bump PR in every protocol repository that pins swarm-core
   (the failing check names each place to change), until org-bot does it
   (#208). Contributions are accepted under the licence of the directory they
   land in (inbound = outbound, below). Write clean implementations against public ns-3 interfaces rather
   than copying from ns-3's `src/aodv`, `src/olsr` & co.; third-party code keeps
   its own licence and lands only with its provenance recorded.
2. **POD wire messages.** Control headers are simulator-independent POD structs
   with bounds-checked little-endian readers/writers, a leading version byte, and
   deterministic roundtrip + fuzz tests.
3. **No module named `core`.** It collides with ns-3's `src/core`; the shared
   module is `swarm-core` (`#include "ns3/swarm-core-module.h"`).
   `ns3-build-contrib` refuses the name. **Every protocol builds on
   swarm-core**, AntHocNet included: its `core/` on swarm-core's dual-licensed
   `core/`, its ns-3 adapter on `SwarmRoutingBase`; what a protocol needs and
   the base lacks is promoted into swarm-core (maintainer decision,
   swarm-routing/ns3-swarm-core#14).
4. **Determinism.** Fixed `--seed=<N>` ⇒ byte-identical output. Comparisons are
   paired per-seed deltas over ≥ 20 seeds, emitting `##CONFIG##`, `##RUN##`,
   `##BENCH##`, `##DIAG##` lines.
5. **CI hygiene.** Actions pinned by full SHA; buildx caches scoped per profile;
   transient artifacts `retention-days` ≤ 7. Every job that runs steps has a
   `timeout-minutes` cap (a job that only calls a reusable workflow cannot take
   one: the called workflow's jobs carry it), and every apt, npm or installer step its own, sized from recent green
   runs; `apt-get update` runs with `--error-on=any` inside a shell retry.
   Ubuntu mirror outages are the usual cause of a red run.
   Every job that runs steps starts with StepSecurity Harden-Runner
   (`step-security/harden-runner`, pinned by SHA, with `timeout-minutes: 2`,
   #164): it records each
   network call, file write and process of the job on the GitHub-hosted
   runner, and in `block` mode allows only the listed egress endpoints, the
   control against a compromised action or dependency sending secrets out.
   Jobs start in `egress-policy: audit`; after about two weeks of audit data a
   job that holds secrets or publishes (release, image push, org-bot,
   repo-settings, pages deploy) moves to `block` with an `allowed-endpoints`
   list copied from the insights of a green run, never guessed. The insights
   are on the StepSecurity page linked from each run's Harden-Runner step
   (and from the job summary). A job that runs entirely in a `container:`
   cannot take it on a hosted runner (it needs sudo on the VM; StepSecurity's
   limitations), so it goes without: today `reusable-ns3-ci.yml`'s `build`.
   Audit is best effort, not a guarantee (#237). Its agent registers each
   job with StepSecurity's API (`agent.api.stepsecurity.io`); when that call
   times out, the job runs on, but nothing is recorded for it. The log then
   shows `error in connecting to https://agent.api.stepsecurity.io/v1
   (attempt 1/3): TimeoutError` three times, `no response from monitor
   endpoint after 3 attempts`, and `fetch policies: API error status 401:
   {"error":"invalid authorization header format"}`. The 401 comes only
   with the failed registration (in every sampled job that timed out, and
   in no other), so it is a consequence, not a token or setting of ours: on
   public repositories the action takes no API key, and there is nothing to
   configure. A sample of 175 hardened jobs in 100 runs across six
   repositories (171 of them on 2026-11-11) found it in 26 jobs (15%), all
   on 2026-11-11 between 15:03Z and 20:05Z, in several
   repositories at once and sometimes in some jobs of a run but not others:
   an outage on StepSecurity's side. So harden-runner stays, in `audit`,
   on every job: it costs seconds, and a failed registration loses only that
   job's audit data (the sampled jobs all ran on and passed). Before a job moves
   to `block`, check on one job that `block` still enforces its
   `allowed-endpoints` when the API is unreachable; until then no job
   relies on it. An insights page missing for a run is put down to an
   outage only when that run's job logs show `no response from monitor
   endpoint`; without that line, look into it. The same search counts it
   again.
6. **Comparator arms** (protocols we did not design) clear three gates before
   their numbers count: a fidelity sheet from the paper, the per-PR delivery
   smoke, and an anchor reproducing the paper's own trend.
7. **Automatic CI targets the ns-3 release ns-3 supports.** ns-3 maintains its
   latest release only (no maintenance branches, no backports), so push, PR
   and scheduled CI build against `ghcr.io/swarm-routing/ns3-dev:latest-<profile>`
   (`reusable-ns3-ci.yml`'s default). Older ns-3 releases run only on demand:
   a manual `workflow_dispatch` that passes `ns3-versions` (a JSON list such as
   `["3.48"]`), on images
   `ns3-containers` publishes once (history) or builds on request. A
   published number pins a versioned `-<sha7>` image instead, never `latest`.

## Issues

Every finding, bug and decision is an issue, never a chat message or a file.

**Papers are cited by their `https://doi.org/<DOI>` link** in public issues,
PRs and docs (maintainer preference, 2026-11-11), read from a record
(`tools/lit-search/lit_search.py confirm`), never typed from memory; a work
without a DOI is cited by its publisher's or institution's page. A public
surface never points into, or names, the private paper library: no paths,
extracted text or file names from it.

**Body shape:** **Context** (evidence, numbers, links) · **Scope** ·
**Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
`swarm-routing/<repo>#N`) · **References**. Children of an epic say
"Part of #N" and are linked as sub-issues.

**Epics are the public plan.** An epic (label `epic`) groups the issues that
deliver one outcome; its children are linked as sub-issues, so its status is
read from them. An open epic is *Planned* (no sub-issue closed) or *In
progress* (at least one closed, as done or not); it becomes *Done* or
*Dropped* only when the epic itself is closed (as completed or as not
planned), so close it once its outcome is delivered. Each public repository's
README lists its epics in an `## Epics` section, and
[ROADMAP.md](ROADMAP.md#epics) and the org profile list them all, generated by
[`tools/epics/epics.py`](tools/epics/epics.py), never typed; private
repositories never appear. Whoever changes an epic (opens,
closes, renames or re-scopes it, adds or removes its `epic` label) or one of
its sub-issues (closes, reopens, adds or unlinks it) refreshes those lists in
that PR or the next one. That needs this repository checked out next to
theirs and `gh` logged in (or `GH_TOKEN` set); the README to refresh is the
one of the repository that owns the epic, even when the sub-issue lives
elsewhere:

```bash
python3 ../.github/tools/epics/epics.py readme .            # in the repository that owns the epic
python3 tools/epics/epics.py roadmap ROADMAP.md             # here, in .github
python3 tools/epics/epics.py profile profile/README.md      # here, in .github
```

The weekly `epics` workflow here only reports drift: it opens, or comments
on, one issue when any list no longer matches the issues. Every open
sub-issue carries `priority:*` and `model:*`, so a contributor, or the AI
agent working with them, can pick one up and follow that repository's
`AGENTS.md`.

**Labels** ([`labels.json`](labels.json), applied by
[`sync-labels.yml`](.github/workflows/sync-labels.yml) in each public
repository; private repositories run no pipelines and no
automatic CodeRabbit review, so a new label is added there by hand):

| Kind | Rule | Labels |
|---|---|---|
| Type | exactly one; umbrellas add `epic` | `bug`, `enhancement`, `chore`, `documentation`, `verification` (+ `question`, `handoff`) |
| Area | one or more | `protocol`, `adapter`, `ns3`, `benchmark`, `observability`, `packaging`, `learn-site`, `literature` |
| Model | exactly one, a suggestion: what a wrong first pass costs, not code volume; only models a Claude Pro plan includes (maintainer decision, #280) | `model:haiku-5.5` (mechanical), `model:sonnet-5.5` (plumbing, tooling, docs), `model:opus-5.5` (protocol semantics, root cause, adapter work, architecture: write the design first) |
| Priority | exactly one on non-epic issues; never on an epic | `priority:P1` (blocks the current wave's release, breaks `main`, or invalidates published numbers; a protocol's gated v0.2.0 issue while its wave is current), `priority:P2` (gates a result or feature), `priority:P3` (valuable, not blocking). Infrastructure work holds at most 30% of the work in flight (maintainer decision, #262) |
| Release | only when a release in the repository's own ladder (its `docs/roadmap.md`) gates the issue; never on infrastructure-track work that only rides along | `release:v0.1.0`, `release:v0.2.0`, `release:v0.3.0`, `release:v0.4.0`, `release:v1.0.0` (shared, from `labels.json`); a repository with a longer ladder (AntHocNet) keeps its own `release:vX.Y.Z` labels |
| Contributor | any number, set by a maintainer when an outside contributor can pick the issue up | `good first issue` (small, well scoped, needs no history), `help wanted` (outside help welcome) |

GitHub lists open `good first issue` issues on each repository's Contribute
page (`/contribute`); `help wanted` issues are found through the label filter
(`/issues?q=is:open+label:"help wanted"`). Either says in its body what a
newcomer needs (files, the check that proves it, the repository's
`AGENTS.md` build commands).

`migrated` marks an issue cloned from `danieljoppi/AntHocNet` during the split;
its body starts with *Migrated from `danieljoppi/AntHocNet#N`*. It takes the
`release:` label of the target repository's ladder, not AntHocNet's (ROADMAP
"Releases"; decision 2026-11-11).

**Handoffs are issues** (template *Handoff*, label `handoff`). A session that
continues handed-off work starts from the newest open `handoff` issue for that
work; a new task starts from the request. A session that continued a handoff
and ends with work in flight updates that issue instead of opening another;
the session that completes the work closes it, and any older handoff it
superseded (AntHocNet ADR-0013 item 5 and its 2026-11-12 amendment; the agent
defaults in `templates/agents/agent-defaults.md`).

## Pull requests

- Branch from `main` (`claude/<short-topic>` for agent work), one focused
  change per PR.
- **Every change goes through a PR to `main`**, opened as soon as the branch is
  pushed, so all work is tracked.
- **PRs are squash-merged** — the only merge method enabled in every repo. The
  PR title becomes the commit on `main`, so it is a lowercase Conventional
  Commit: `type(scope)!: subject`, scope and `!` optional, subject starting
  lowercase. Types: `feat`, `fix`, `docs`, `style`, `refactor`, `perf`, `test`,
  `build`, `ci`, `chore`, `revert` (the list `reusable-pr-title.yml` enforces).
- Merge when CI is green. A repository that merges through a merge queue
  (`merge_queue = true` in its `[settings]`, #130) is not updated by hand: add
  the PR to the queue by enabling auto-merge with the squash method (the
  merge button, `gh pr merge --auto --squash`, or a GitHub tool's auto-merge
  call); a direct merge (`PUT pulls/<n>/merge`) is refused there with
  HTTP 405 "Changes must be made through the merge queue", so agents never
  retry it. The queue tests
  it on top of `main` and the PRs ahead of it, then merges it. Every workflow
  that produces a required check runs `on: merge_group` there; the reusable
  PR-title check skips itself on a merge group (a skipped check passes) and
  the org-sync check judges the group's own change against its base.
- **`main` takes no direct push** in any repo: the `main` ruleset requires a
  PR and the required checks. It does not require an up-to-date branch
  (`strict_required_status_checks_policy` is off in every profile, maintainer
  decision 2026-11-11): a PR behind `main` merges once its checks pass. Bots push `bot/<name>`
  branches and open PRs; releases go through the bump PR (Cutting a release).
- Where there is no queue yet, a PR behind `main` may merge as it is. Update
  it first when `main` changed what it touches (a template, a workflow, a
  required check), and then merge PRs one at a time, each after its CI on
  the updated branch.
  `tools/pr-status/pr_status.py merge
  REPO#N [REPO#N …]` does exactly that: in the order given (repositories
  independently), it merges a PR GitHub reports `behind` as it is, and
  updates it first (`PUT pulls/<n>/update-branch`) only where the ruleset
  requires an up-to-date branch or with `--update` (you judged that `main`
  changed what it touches); it waits for every check on the head
  and for CodeRabbit's review (below), squash-merges with the title `<PR title> (#n)`, and only then moves on to
  that repository's next PR. It never merges while a required check is
  missing on the head, and stops and reports on a failing check (a workflow
  that ended in `startup_failure` counts as one), an unresolved review thread, a conflict, a draft or a refusal, and never
  reruns a check or resolves a thread itself (`--dry-run` says what it would
  do). Never force-push a branch someone else pushed. A behind `bot/release` PR is the exception:
  dispatch `bump` again (Cutting a release). `merge` does not enter a merge
  queue yet, and it waits on (or stops at) checks no ruleset requires, such
  as `codecov/patch` or `dco` (#196): in a merge-queue repository enable
  auto-merge instead.
- **CodeRabbit's review comes before the merge** (#238). CodeRabbit reviews
  each PR once, when it opens (#37), usually within 10 to 20 minutes; it is
  not a required check, so auto-merge and a merge queue do not wait for it,
  and a PR whose required checks finish first merges unreviewed (CodeRabbit
  then reports "Review failed: The pull request is closed"). So enable
  auto-merge only once CodeRabbit has reviewed and every thread it opened is
  answered and resolved: `python3 -I tools/pr-status/pr_status.py wait
  --review REPO#N` waits for its review (a review on the PR, or its `CodeRabbit`
  check run completed on the head) and `pr_status.py merge` waits for it
  before reading the threads. Both give up after `--review-timeout`
  seconds from the PR's opening (default 1800) and go on with a warning,
  so an absent or failing CodeRabbit never holds a PR. A PR that merged
  before its review is reviewed after the fact: comment
  `@coderabbitai review` on it, and fix what it finds in a follow-up PR.
  Making CodeRabbit's check required was not chosen: a required check has
  no time-out, so a CodeRabbit outage would stop every merge. Instead, the
  org's own **review gate** (#294) is the check that waits: the
  `review / coderabbit` job (`templates/workflows/review-gate.yml` in every
  adopting repository, on `reusable-review-gate.yml` and `pr_status.py
  gate`) passes once CodeRabbit has reviewed the PR, once it says it will not
  (a skipped review, a rate limit, a used-up quota), for a draft, or 30
  minutes after the PR opened, leaving one comment then (maintainer
  decisions on #294); in a merge group it passes at once. Where
  `review / coderabbit` is in `[settings]` `required_checks`, auto-merge and
  the queue wait for the review by themselves, org-bot's PRs included. Since
  2026-11-12 it is required in every adopting repository (applied by
  `repo-settings`), so there auto-merge may be enabled when the PR opens;
  where it is not listed in the live rules yet, the rule above still holds.
- **Only the required checks gate a merge.** They are the ones in the
  repository's `[settings]` `required_checks` (live:
  `gh api 'repos/{owner}/{repo}/rules/branches/main'`). A red or pending
  report-only check (Codecov, SonarQube Cloud, Scorecard) is read and
  triaged, never a reason to hold a PR whose required checks are green
  (GitHub then reports the merge state `unstable`, which is mergeable).
  `dco` is report-only too, but a red `dco` on an outside contributor's
  commit still holds the PR until that author signs off (Outside
  contributions); only its failure on the maintainer's or an agent's
  commits (#212) is ignored.
- `Closes #N` in a PR body closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.

## Outside contributions

Contributions from outside the org are welcome in every public repository:
open an issue first for anything larger than a fix, fork, branch, and open a
PR to `main` (the [Pull requests](#pull-requests) rules apply; CI runs on a
fork's PR once a maintainer approves its workflows, which every outside
contributor's fork PR waits for).

**Inbound = outbound.** A contribution is licensed exactly as the directory it
lands in, by that repository's `LICENSING.md` row: in `core/` and the
standalone tooling (`tools/`, Python CLIs, CI and image scripts) under
`MIT OR GPL-2.0-only`, recipient's choice; everywhere else (ns-3 modules, the
site, docs, data) under `GPL-2.0-only`. A contribution that cannot be offered
under its directory's licence belongs elsewhere or is declined; code from
another project keeps its own licence and lands only where that licence fits,
with its provenance recorded (invariant 1).

**Developer Certificate of Origin.** Every commit certifies the
[Developer Certificate of Origin 1.1](https://developercertificate.org/), whose
full text is in [`DCO`](https://github.com/swarm-routing/.github/blob/main/DCO) at the root of `swarm-routing/.github`, by carrying a
`Signed-off-by` trailer with the commit author's own name and email:

```text
Signed-off-by: Ada Lovelace <ada@example.org>
```

`git commit -s` adds it (name and email must be the commit's author's; case
and extra spaces do not matter). Missed one? `git commit --amend -s --no-edit`
for the last commit, `git rebase --signoff HEAD~N` for the last N, then
`git push --force-with-lease` to your fork's branch. `--signoff` signs as you,
so it fixes only commits you authored; a commit someone else authored needs
that author's own sign-off. The `dco` check (`reusable-dco.yml`, placed in every repository
by org-sync as `.github/workflows/dco.yml`) lists any commit without a
matching sign-off and prints these commands. Commits by the org's members and
collaborators are exempt, and so is a commit by a GitHub bot account (a login
ending in `[bot]` or a `…[bot]@users.noreply.github.com` author email, such as
the `github-actions[bot]` release bump commit of `reusable-release.yml`) on a
PR opened by one of the org's bots (the org App `swarm-routing-bot[bot]`,
Dependabot, `github-actions[bot]`) or by a member, collaborator or anyone with
write access. Anyone can write a bot's email into a commit, so a bot-authored
commit on an outside contributor's PR is not exempt: it needs a sign-off like
any other (#368). A merge commit that adds nothing beyond its parents (an
"Update branch" merge) is exempt too; a merge that resolves a conflict with new text or
carries a change of its own needs a sign-off like any other commit.
Maintainer and agent commits are made from the maintainer's own account,
under the licence grant already recorded in AntHocNet ADR-0028. **An AI agent
never adds a `Signed-off-by` trailer**, for the maintainer, for itself or for
anyone else: a sign-off is a person's own certification. Instead, an agent
commit (one whose message carries a `Claude-Session:` trailer) is exempt when
the PR's author is the repository's OWNER, a MEMBER or a COLLABORATOR, or has
write access to it (a private org member shows as CONTRIBUTOR in the PR
event, so the check also asks for the author's permission): the
person who opened the PR certifies its contents by opening it (maintainer
decision, #212). The same commit on an outside contributor's PR is not
exempt; it needs its author's own sign-off, since no one signs off on anyone
else's behalf. So **an agent never pushes to an outside contributor's PR**: a
change is asked of the contributor, or made in a follow-up PR after the merge
(maintainer decision, #288). If someone else pushes to such a PR while it is
in a merge queue, disabling auto-merge does not take it out: remove it from
the queue, and enqueue it again only once `dco` has passed on the new head
(swarm-routing/BeeAdHoc#79).

The sign-off is the recorded grant AntHocNet
[ADR-0028](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)
requires before outside code enters a dual-licensed `core/` ("Provenance is a
gate, not a courtesy"; "A new external contributor to `core/` must agree to
both licences"): DCO clause (a) or (b) states the contributor has the right to
submit the work under the licence indicated in the file, which is its SPDX
line, and clause (d) makes the record public and permanent. No separate
agreement is needed.

**Copyright lines.** Keep the org's copyright line and the SPDX line as they
are; to be named, add your own line beneath the org line:

```cpp
// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// Copyright (c) 2026 Ada Lovelace
// SPDX-License-Identifier: MIT OR GPL-2.0-only
```

`tools/checks/check-headers.py` accepts any number of such lines as long as
the org line comes first and the SPDX expression is exactly the directory's.

## Automation

Two scheduled workflows in this repository keep the org current. Both are dry
runs until their secret is set, and the secrets belong to the maintainer:

| Workflow | What it does | Secret |
|---|---|---|
| `org-bot` (daily, and on every push that changes `templates/` or a generator; task `swarm-core-pin` also every three hours) | Opens one PR per repository when its `## Epics` section (and, here, ROADMAP.md and the profile) or its org-managed files have drifted, or when Zenodo holds a concept its CITATION.cff and `zenodo_concept` do not name yet (task `zenodo`, #232), or when swarm-core `main` changed `core/` since a protocol repository's pin (task `swarm-core-pin`, #208: `check-swarm-core-pin.py --bump` rewrites every occurrence of the old commit; one PR per repository on `org-bot/swarm-core-pin`, updated in place when swarm-core moves again). The same change is never proposed twice; an older bot PR is closed as superseded, so a repository has at most one open bot PR per task. Where `main` has a merge queue (`merge_queue = true`), it enables auto-merge on its own PR, which enters the queue once green and lands with no hand step (#178); a repository without a queue is logged and its PR is merged by hand | The org GitHub App (`BOT_APP_ID`, `BOT_APP_PRIVATE_KEY`; below), else `ORG_BOT_TOKEN`: a fine-grained token on the org, all repositories, with Contents, Pull requests and Workflows read and write |
| `zenodo` (daily) | See Releases and DOIs below | `ZENODO_TOKEN` |
| `repo-settings` (daily check; apply on every push that changes `templates/rulesets/` or the tool) | Keeps each repository's settings equal to the `[settings]` table of its `.github/org-sync.toml` and its profile in `templates/rulesets/` (`tools/repo-settings/repo_settings.py`): description, homepage, topics; merge settings (squash only, PR title and body as the commit, delete the branch, auto-merge allowed, always suggest updating PR branches) and features (issues on; wiki, projects, discussions off); the `main` ruleset and the `release-tags` ruleset (v* tags cannot be deleted, force-pushed or moved); security features, only ever turned on (Dependabot alerts and security updates, secret scanning and push protection, private vulnerability reporting, CodeQL default setup except where the repository runs its own CodeQL workflow; on a private repository the free plan offers only the Dependabot ones, the rest is reported unsupported); the Actions policy (selected actions: GitHub's own plus the list in `templates/rulesets/defaults.json`, `GITHUB_TOKEN` read-only by default, Actions may not approve PRs, and a fork PR's workflows wait for a maintainer's approval whenever its author is neither a collaborator on the repository nor a member of the org: `all_external_contributors`, the strictest of GitHub's three fork-PR approval policies, on public repositories; a private repository's fork-PR workflow setting is not managed); and, where enabled, a `release` environment with the maintainer as required reviewer (where `release_environment = false`, an existing `release` environment's reviewers and wait timer are removed instead). The daily check opens, updates or closes one `[settings]` drift issue; a private repository's values are never printed. It never deletes a ruleset or an environment, never turns a security feature off, and only manages the rulesets named in its profiles | The org GitHub App, else `ORG_BOT_TOKEN` (a fine-grained token). Either needs, on every repository, besides org-bot's: **Administration: read and write** (every settings write, and reading rulesets, security and Actions settings), **Contents: read** (each `org-sync.toml` and the workflows), **Actions: read** (the `release` environment), Metadata: read. No Dependabot alerts, Secret scanning alerts or Code scanning alerts permission is needed: those cover the alerts, not the settings. The App already has Administration: write; check it also has the reads. Until the token has them, apply reports `refused` (or `unreadable`) and only the check runs |

Each adopting repository's `org-sync` check (`reusable-org-sync-check.yml`)
judges a PR by its own change only (#159): on `pull_request` and
`merge_group` it runs `org_sync.py check --changed-only` against the base, so
an item fails only when it drifts at the PR's head and either did not drift at
the base (the same templates rendered on the base's tree: a config change
whose render the PR did not apply) or the PR edited it by hand (changed the
managed file, deleted a seed, or touched a line inside a managed section).
Editing `.github/org-sync.toml` alone (a `[settings]` key such as
`required_checks`) is not a hand edit of every item. Drift a newer template
left on the base is a `::warning::` annotation per item, naming it, and the
check passes. A template change here therefore never turns red the open PRs
of the adopting repositories; they merge as they are, and org-bot's refresh PR
brings the templates in. A push to `main` keeps the full check, so drift there
stays visible until the refresh PR merges. A caller that wants the full check on
PRs too passes `full-check-on-pr: true`.

**A change to an org-managed section is a template change here, never a hand
edit in each repository** (#236). Text between `org-sync:begin/end` markers
(the AGENTS.md org sections, the README badges, the CodeRabbit head and
tail, …) and the other managed (non-seed) items come from
`templates/`. One per-repository value reaches a managed section: the
CodeRabbit head's `path_filters` list is the org's entries followed by the
repository's `coderabbit_path_filters` (a list of globs in
`.github/org-sync.toml`, e.g. `["!results/**"]` for generated data), since
the list sits inside the head and a hand-added entry would be drift. To change them across the org, open one PR here that edits the
template; after it merges, org-bot opens each adopting repository's
`bot/org-sync` refresh PR (`org_sync.py apply`), which is the only PR that
brings the change in. Do not open a hand-edited PR per repository alongside
it: the check renders the templates of this repository's `main` as they are
when it runs (`org-ref`), so a hand edit pushed while the template PR is
still open is drift, red on `check / org-sync`, and it stays red after the
template merges until the check runs again on that branch; org-bot never
pushes to a branch it did not open (2026-11-11: ten PRs sat red for about
2.5 hours after #230 merged, until each branch was updated and re-applied
by hand). If such a PR exists anyway, close it in favour of org-bot's, or
update its branch from `main`, run `org_sync.py apply .` on it (from a
checkout of `swarm-routing/.github` next to the repository:
`python3 ../.github/tools/org-sync/org_sync.py apply .`) and push. Seeds
(SECURITY.md, the Makefile, LICENSING.md, CITATION.cff, …) are the
exception: once written they belong to the repository, a template change
never reaches them and org-bot's PR does not bring it in, so a seed is
changed in each repository (or rewritten from the template with
`org_sync.py reseed FILE`). Text a
repository owns outside the markers is likewise edited in that repository.

A repository with its own `.github/ISSUE_TEMPLATE/` (a form of its own, as
ns3-containers' *Image request*) loses the org's default forms: GitHub uses
the repository's folder instead. It sets `forms = true` in its
`.github/org-sync.toml`, and every org form here (`ISSUE_TEMPLATE/*.yml` but
`config.yml`) becomes a whole file there, so a form change here reaches it
through org-bot's refresh and a stale copy turns `check / org-sync` red. Its
`config.yml` and its own forms stay its own (#318).

Settings are changed by PR, never by hand: edit the repository's `[settings]` (or a profile here) and the next apply writes it (a profile change applies on push here; a `[settings]` change in another repository applies when `repo-settings` is dispatched with mode `apply` after its merge); a hand edit, in the UI or by a direct API write, shows up as drift the next day. A required check must run on every PR (no `paths:` filter; skip the work inside a gate job instead), or the PRs it skips can never merge, and its name must match the check run's name exactly. An org-level ruleset (an org-owner setting) can add a floor every repository inherits, including new ones before their `[settings]` land.

A repository's `[settings]` can override what its profile gives it: `features = { has_wiki = true }` (any of `has_issues`, `has_projects`, `has_wiki`, `has_discussions`, `allow_auto_merge`, `allow_update_branch`), `security = { codeql_default_setup = false }` (false leaves that feature alone; it is never turned off), and `release_environment = true` (or `false`, below). `merge_queue = true` adds a merge queue to the `main` ruleset (squash; every PR of a group must pass, `ALLGREEN`; groups of 1 to 5 PRs, checks running for at most 5 queued PRs at once; 120 minutes for the required checks; `MERGE_QUEUE` in the tool); a table such as `merge_queue = { check_response_timeout_minutes = 60 }` overrides any of them, within the API's bounds. It needs `required_checks`, GitHub offers it only on public organization repositories, and every workflow that produces a required check must also run `on: merge_group` (with a path filter or a `changes` job, diff against `github.event.merge_group.base_sha`, since a merge group has no `pull_request`), or the queue waits for a check that never comes: `repo-settings` refuses the repository, before writing anything, while a workflow that runs on `pull_request` and has a job named (or with the id) a required check's first ` / ` segment lacks that trigger (a `${{ … }}` in a job name, as in a matrix, matches any text; reusable `workflow_call`-only workflows are not counted). The daily `check` also lists each check that ran on the head of `main` (check runs not skipped, and commit statuses) but is neither in `required_checks` nor matched by `optional_checks` (fnmatch patterns, e.g. `optional_checks = ["codecov/*", "Analyze (*)"]`), one `<repo>: unrequired check: <name>` line each; it is information, not drift, and the workflow keeps one `[settings] <repo>: …` issue per repository listed (#177). Require a check only if it runs on every PR; mark the rest optional. The Actions policy allows only the actions listed in `templates/rulesets/defaults.json` (`selected_actions.patterns_allowed`, besides GitHub's own and local ones): a workflow that starts using a new third-party action needs its `owner/repo@*` added there in the same change (in another repository: merged here first), or `repo-settings` refuses that repository (the check names the action) rather than switching it to a policy that would break its CI. The `release` environment (required reviewer: the maintainer) is created only where `release_environment = true`. **It is off for now, by maintainer decision (2026-11-11):** no repository sets it to `true`, so a release publishes without waiting for an approval. `release_environment = false` turns an existing gate off: `apply` removes the `release` environment's required reviewers and wait timer and keeps its deployment branch policy (an environment is never deleted); with the key absent, an existing environment is left as it is, and a repository without one gets GitHub's unprotected `release` environment the first time a job names it. To turn the gate back on, set `release_environment = true` in the repository's `[settings]` and dispatch `repo-settings` with mode `apply`; the reusable release workflow's publish job already names `environment: release`. The `release-tags` ruleset does not restrict who creates a v* tag: the release workflows push tags with the org App's token or, without it, `GITHUB_TOKEN`, which cannot be a ruleset bypass actor, so a creation rule would block every release.

The bot's PRs are generated content only; merge them when CI is green. You
still refresh the epic lists in your own PR when you change an epic: the bot
catches what was missed, it is not the process.

### Benchmark cells

Each protocol repository benchmarks its own changes; `swarm-routing/benchmarks`
records released versions (#156). One cell workflow serves every repository:
`reusable-benchmark-cell.yml` (#157), called by a thin `workflow_dispatch`
caller in the protocol repository (its header has the caller), and dispatched
cell by cell by `ns3-campaign` (`swarm-routing/ns3-tools`). A cell is one
harness invocation in one image, on one commit:

| Input | Meaning |
|---|---|
| `image` (required) | The image by digest, `ghcr.io/<owner>/<name>@sha256:<64 hex>`, never a tag |
| `source_sha` (required) | The caller repository's 40-char commit. Every cell checks it out whatever ref it was dispatched at, and fails unless `HEAD` is exactly that commit, so a campaign dispatched over hours from a moving branch still tests one commit (AntHocNet#867) |
| `harness`, `args` | The `./ns3 run` program and its flags, verbatim (a literal `$GITHUB_WORKSPACE` is expanded to the checkout) |
| `seeds` | `<first>-<last>`, appended as `--firstRun=<first> --runs=<count>`; empty when the args carry their own |
| `cell` | The cell's name, for the job and the log |
| `modules`, `dependencies`, `stage` | Build mode only: the caller's modules, and dependencies pinned as `name=owner/repo@<40-char commit>[:subdir]`, built in the job by `ns3-build-contrib` on an ns3-dev `image` |

Without `modules`, `dependencies` or `stage` the cell is **prebuilt**: `image`
is a campaign or release image from `reusable-ns3-image.yml` whose labels say
it was built from the caller's repository at `source_sha`, and the harness runs
with `./ns3 run --no-build`, so every cell of a campaign runs one binary.
Published numbers use this mode. Every cell ends its `results.txt` with
`##ARGS##` and one `##PROV## commit=… ref=… run_id=… attempt=… image=… profile=…
harness=… base=… base_tag=… build_profile=… modules=…` line (AntHocNet's
fields): `ns3-campaign collect` rejects a cell whose commit or image digest is
not its plan's. The `benchmark-cell` artifact is kept 7 days; a released run is
collected into `swarm-routing/benchmarks`, which keeps it.
`benchmark-cell-selftest.yml` runs one build-mode cell (ns3-tools'
`routing-bench` at a pinned commit, OLSR, 2 seeds) on every PR that changes
the workflow.

**Callers follow the safe pattern** (#160). A cell checks out and runs the code
at a commit it is given (`source_sha`), and a `workflow_dispatch` run does that
in the default branch's context, whose Actions caches every other workflow of
the repository shares. Code at that commit could therefore seed a cache that a
trusted run (a release, `main`'s CI) later restores, which is the cache
poisoning CodeQL flags (it did on `benchmark-cell-selftest.yml`, #158). The
rule, which `reusable-benchmark-cell.yml` follows so its callers inherit it:

- **No Actions cache.** The cell job sets `cache-mode: none`, so the cache
  service refuses every restore and save in it (a called workflow never gets
  more cache access than that), and no step asks for one (no `actions/cache`,
  no `setup-*` `cache:`, no buildx `type=gha`), least of all keyed by a caller
  input such as `source_sha`. The mode matters even with no cache step: code
  run by `stage` or the harness could alter a later action step, which holds
  the runtime token, and save a cache from there. The caller adds no cache
  step and no other job to its cell workflow, and sets `cache-mode: none` on
  its calling job too (the caller in the workflow's header does). actionlint
  does not know the key yet; ignore that one message in `.github/actionlint.yaml`
  as this repository does.
- **Least permissions.** The caller grants `contents: read` and
  `packages: read` only, and passes no secrets (no `secrets: inherit`), so the
  code at `source_sha` holds a read-only token and nothing else.
- **No credential left behind.** The checkout uses `persist-credentials:
  false`, and the cell logs out of `ghcr.io` once the image is pulled, before
  any step runs the checked-out code.
- **`workflow_dispatch` only.** No `push`, `pull_request_target`,
  `workflow_run` or `issue_comment` trigger: only someone with write access
  dispatches a cell, on a commit of their choosing. The self-test here runs on
  `pull_request` only: a cache a PR run saves is scoped to the PR's merge ref,
  so it cannot poison `main`'s (a PR run can still restore `main`'s caches, so
  a cache is never a place for secrets; the cell job's `cache-mode: none`
  turns both off anyway).

### The bot's GitHub App

`org-bot`, `repo-settings` and `repo-metadata` get their token from
`.github/actions/bot-token` (#21): an installation token of the org's GitHub
App when the `BOT_APP_ID` and `BOT_APP_PRIVATE_KEY` org secrets are set, else
`ORG_BOT_TOKEN` (`repo-metadata`: `REPO_SETTINGS_TOKEN`, then
`ORG_BOT_TOKEN`). `ORG_BOT_TOKEN` is the maintainer's personal token, so every
workflow using it shares his 5,000 requests an hour (it ran out on
2026-11-10); the App has its own, larger limit and is nobody's account. PRs
opened with either token run CI, unlike those opened with a workflow's
`GITHUB_TOKEN`. With the App, the bot commits as `<app-slug>[bot]`
(`<user id>+<app-slug>[bot]@users.noreply.github.com`); with the personal token
it keeps `github-actions[bot]`. Each run logs which token it used: a notice
`bot token: GitHub App <slug>[bot]`, or `the GitHub App is not configured …;
using the fallback token`, or a warning when the App's token could not be made
(the run then falls back too).

Creating the App (an org owner, once):

1. Organization **Settings → Developer settings → GitHub Apps → New GitHub
   App**. Name `swarm-routing-bot` (the slug, and so the commit author, follows
   the name); homepage `https://github.com/swarm-routing`.
2. **Webhook**: untick *Active* (no webhook URL, no events).
3. **Repository permissions**, Read and write: Actions, Administration,
   Contents, Dependabot alerts, Environments, Issues, Pull requests, Secret
   scanning alerts, Workflows. Metadata: Read-only (set automatically). No
   organization or account permissions.
4. **Where can this GitHub App be installed?** *Only on this account*. Create
   the App.
5. On the App's page: note the **App ID** (or the Client ID; either works);
   **Private keys → Generate a private key** downloads a `.pem`.
6. **Install App** → `swarm-routing` → **All repositories** → Install.
7. Organization **Settings → Secrets and variables → Actions → New
   organization secret**: `BOT_APP_ID` = the App ID, and
   `BOT_APP_PRIVATE_KEY` = the whole `.pem` file, both with *Repository
   access: All repositories*. Delete the `.pem` from disk.
8. Run `org-bot` (dry run) and `repo-settings` (`plan`) from the Actions tab:
   the *Bot token* step must log `bot token: GitHub App swarm-routing-bot[bot]`.
9. After the App's runs have worked for a few days, delete the
   `ORG_BOT_TOKEN` (and `REPO_SETTINGS_TOKEN`) secrets and revoke the personal
   token. The fallback then does nothing, and can be removed in a later PR.

## Releases and DOIs

A citable repository carries a `CITATION.cff` whose `doi:` is its Zenodo
**concept** DOI (it always resolves to the newest version; #45). Zenodo's
GitHub integration archives each published release and mints its version DOI.
The daily `zenodo` workflow here (`tools/zenodo/zenodo.py`) is the check behind
it:
- it lists every such repository's releases against every version of its concept;
- it archives a release still missing after 12 hours as a new version, with
  that tag's `CITATION.cff` metadata (title, abstract, authors, keywords) and
  its `github.com/swarm-routing/<repo>/tree/<tag>` link;
- it never adds a release older than the newest archived one, since that would
  become the concept's newest version. The run fails and opens an issue
  instead.

Its Zenodo token (`ZENODO_TOKEN`, scopes `deposit:write` and `deposit:actions`)
belongs to the maintainer. Without it every run is a dry run. Never type a DOI:
read it from Zenodo (`zenodo.py status --repo swarm-routing/<repo>`).

**The push path** (#232). Zenodo's GitHub integration *pulls*: it fetches
each release from GitHub as the maintainer's account, and fails when that
account's quota is spent (below). A repository can instead have its release
job *push* the release to Zenodo: `reusable-release.yml` with `zenodo: true`
and the `ZENODO_TOKEN` secret passed in (its header has the caller lines).
Its `zenodo` job runs after the GitHub release is published, in the
`release` environment, and runs `zenodo.py publish-release`: it uploads the
release's own assets (the build's files, `SHA256SUMS`, the SBOM, the
provenance) with the release commit's `CITATION.cff` metadata, as the first
version of a new concept for a first release, else as a new version of the
repository's concept (so the concept DOI never changes). It is idempotent (a
tag already on Zenodo, archived by the integration or by an earlier run, is
reported and nothing is written), retries a 429 or 5xx with backoff, writes
the concept and version DOIs to the job summary, and fails the job when
Zenodo refuses; the GitHub release stays published either way. It is opt-in
per caller (`zenodo` defaults to false), so repositories move over one at a
time:
1. the caller adds `zenodo: true` and `ZENODO_TOKEN: ${{ secrets.ZENODO_TOKEN }}`;
2. the maintainer turns **off** Zenodo's GitHub integration for that
   repository (Zenodo, *GitHub* in the account menu, the repository's
   switch), before its next release, or that release is archived twice
   (the integration's copy is a source zip; the push uploads the assets);
3. the daily `zenodo` run stays the backstop: a release whose `zenodo` job
   failed is archived by `sync` after the 12-hour grace period, or re-run the
   job. Not a *first* release: with no concept yet, `sync` has nothing to add
   it to, and the daily run only reports it (`orphans`, an issue once past
   the grace period). Re-run the release run with "Re-run all jobs", or
   dispatch `gh workflow run zenodo.yml -R swarm-routing/.github -f mode=create
   -f repo=<repo> -f tag=<tag>` (a dry run first with `-f dry-run=true`;
   "When Zenodo fails a release", below).

**After the upload** (#232). The job writes the concept to its outputs
(`zenodo-concept`, `zenodo-doi`) and checks the release commit against it with
`zenodo.py record`: the `doi:` of `CITATION.cff`, `zenodo_concept` in
`.github/org-sync.toml` (which renders the README's DOI badge and citing
section) and any DOI badge in the README must all name the concept Zenodo
returned. A missing one, as after a first release, which makes the concept,
is a notice: org-bot's `zenodo` task (daily, or dispatch `org-bot` with task
`zenodo` and the repository) runs `zenodo.py record --write`, which writes
`zenodo_concept` and the `doi:` and `identifiers:` lines of CITATION.cff from
the Zenodo record that links the release tag, then `org_sync.py apply` for the
badge and the citing section, and opens the PR; nobody types the DOI. A
different concept fails the job (the release and the archive stand) and fails
org-bot's run for that repository, until the maintainer decides which is
right. The task only reads Zenodo, and also covers a repository still on the
integration.

`zenodo-sandbox: true` sends the same upload to sandbox.zenodo.org (with a
sandbox token as `ZENODO_TOKEN`), to prove the path before a real release.
`release-selftest.yml` runs the command on its dry run's assets against a
fake Zenodo on every change to the release workflow or `tools/zenodo/`.

**Who can read `ZENODO_TOKEN`.** It is the maintainer's personal Zenodo
token. Settings as code (`[settings]`, `templates/rulesets/`) do not manage
secrets, so its scope is the maintainer's to set, in GitHub's settings: as an
organization secret, its repository access is *Selected repositories*
(`.github` for the daily run, plus each repository that opted into the push
path), never *All repositories*. A repository may hold it as a secret of its
`release` environment instead: the `zenodo` job runs in that environment, so
the environment's secret takes the place of the passed one, and no job
outside the environment reads it.

A repository's README shows AntHocNet's three badges through org-sync, each
only once its target exists: **Release** when a workflow calls
`reusable-release.yml`, **Cite** when it has a `CITATION.cff`, and **DOI**
when its `.github/org-sync.toml` names the concept as top-level
`zenodo_concept = "<record id>"`. `citation = true` (also top-level) seeds a
`CITATION.cff` from `templates/CITATION.cff.in`: title, abstract (the
`[settings]` description, else `description`), the maintainer's author entry
as in AntHocNet's, the whole work's licence (GPL-2.0-only unless the whole
repository is dual: a CFF list reads as a choice), the repository URL and the
version in the repo's `.cz.toml`; add `"CITATION.cff:^version:"` to its
`version_files` so each bump keeps it current. The concept exists only after
the first release is archived; org-bot's `zenodo` task then opens the PR that
sets `zenodo_concept` and CITATION.cff's `doi:` from Zenodo's record (above),
so the daily check here covers the repository.

A repository is cited as AntHocNet is. `citation = true` also manages the
README's **Releases & citing** section (`<!-- org-sync:begin citing -->`):
how releases ship, the concept DOI (or, before the first archived release,
that there is none yet), a pointer to each release's version DOI on its
Zenodo record (never a hand-kept row per version), the work the repository
implements or builds on, and `docs/fidelity.md` when it exists. That work
comes from `docs/references.bib` once it has an entry (References, below);
until then it is listed once, as `[[references]]` in `.github/org-sync.toml` (type, title,
authors, year, venue, `doi`, a one-line `role`; a work with no DOI gives its
publisher's or institution's `url` and `no_doi`, the reason), and renders
both the README list and CITATION.cff's `references:` (reseed it after a
change). Take every field of a work with a DOI from Crossref, confirmed with
`tools/lit-search/lit_search.py confirm <DOI>`, never from memory; for a work
with none, from its publisher's or institution's record (`fidelity.py bib
entry --url URL`, References below).
`role` is the repository's own line on what the work is for.
`citation_type = "dataset"` (`software` by default) gives a dataset's
`type:` and message; `citation_message = "..."` (one line, no double quotes)
replaces that message with the repository's own, which CITATION.cff then
keeps on `reseed`. `tools/docs-review/check_docs.py` checks a released
repository (a `v*` tag or `zenodo_concept`) for all of it: the DOI badge,
CITATION.cff's `doi:` equal to the concept, the citing section, and for a
protocol a reference per source with a DOI or the reason it has none.

**When Zenodo fails a release.** Zenodo fetches each published release from
GitHub as the maintainer's account, so it shares that account's API rate
quota (5,000 requests an hour, shared by every OAuth token of that user). benchmarks
`v0.1.0` (2026-11-11) failed this way: Zenodo's GitHub page lists the release
as *Failed* with `403 API rate limit exceeded`, and the webhook delivery shows
"An exception occurred". Zenodo keeps a failed release id, so redelivering the
webhook gets `409` and never archives it. The repository's next release is
archived as usual (for a repository without a concept yet, it creates the
concept), but that archives the new release, not the failed one, and the daily
check adds versions only to an existing concept and may skip the older tag.
The failed release itself needs its own recovery: dispatch the `zenodo`
workflow with mode `create`, the repository and the tag (`zenodo.py create
--repo OWNER/NAME --tag vX.Y.Z --publish`; a dry run first, with `dry-run`).
It archives the tag as the first version of a new concept, with its
CITATION.cff metadata (a dataset stays a dataset), refuses when the repository
already has a concept, and prints the concept and version DOIs; org-bot's
`zenodo` task then records the concept (above). The daily `zenodo` run lists every
released repository without a concept (`zenodo.py orphans`) and opens an issue
once its first release is past the 12-hour grace period (#226).

**No polling as the maintainer around a release.** From the bump PR's merge
until Zenodo has archived the release, nothing runs a polling loop on the
maintainer's GitHub account: monitors use webhooks or `subscribe_pr_activity`,
long intervals (minutes, not seconds) and conditional requests (`ETag` /
`If-None-Match`, whose `304` costs no quota). `pr_status.py` backs off when its
token's `X-RateLimit-Remaining` drops below `--min-rate` (default 500), and
`reusable-release.yml` prints the release token's remaining quota in the job
summary before it publishes (a signal only: that token is the job's, not the
maintainer's) (#226).

### References

Each repository keeps one bibliography, `docs/references.bib` (#307, #308):
the works it relies on, one BibTeX entry each. org-sync seeds it with a
commented header and no entry; a repository with nothing to cite keeps it so.
The header holds these rules, so it is managed: the section `bib-header`,
between `% org-sync:begin bib-header` and `% org-sync:end bib-header`
(`templates/references-header.bib`), reaches every repository through
org-bot's refresh, and an edit there is drift. The entries, and any comment
lines of the repository's own after the end marker, stay the repository's
(#343).

- **Roles.** An entry's `keywords` hold its roles: `implemented` (the work the
  repository implements), `restates`, `compared`, `dataset`, `tool`,
  `background`.
- **DOI links first.** An entry gives its `doi`, and a reference to it is
  shown as its `https://doi.org/` link; a `url` only for a work that has no
  DOI. Never the repository's own DOI (CITATION.cff carries it), and only
  public sources: a work is cited by its DOI link, never by where a copy of it
  is kept.
- **Fields come from Crossref, DataCite or Zenodo, never typed.** `fidelity.py
  bib entry DOI --key K --role R` prints Crossref's record as an entry, or,
  when Crossref has none, DataCite's (a university repository's report or
  thesis, a dataset: the type from its `resourceTypeGeneral`); `zenodo.py
  bibtex OWNER/REPO --role tool` prints an org release's concept record as
  `@software`, keyed as the table below says (`--key K` for a repository it
  does not list yet), with its concept `doi` and no `url` or `version` (a
  Zenodo DOI is never looked up through `bib entry`). A work with no DOI (a
  thesis, a report) takes `bib entry --url URL --key K --role R` on its
  repository's landing page: the page's `citation_*` tags and, for a handle,
  the repository's OAI-PMH record (ETD-MS, which names the degree and its
  grantor, else Dublin Core) give an entry with the url (the handle's) and no
  `doi`; a field the record lacks stays out (a thesis whose record states no
  degree is `@misc`), and a page that names a DOI is refused for `bib entry
  DOI` (#342). `bib check --online`
  suggests a DOI for a url-only entry by its title; that match may be another
  work with the same title (a later chapter or article), so check its type and
  year before adopting it. When it is another work, the entry says so with
  `notdoi = {DOI}`, which silences that warning for that DOI only.
- **One key per work across the org.** A key is the fidelity sheets' style,
  the authors' initials and the year (`G02`, `DDG04`); an org release keeps a
  short name. A work that more than one repository cites, and every released
  org repository, has one key everywhere, chosen to need the fewest renames
  and never to change a fidelity sheet's `[KEY]` citations:

  | Work | DOI | Key |
  |---|---|---|
  | AntHocNet (org release) | https://doi.org/10.5281/zenodo.20981979 | `AHN` |
  | ns3-swarm-core (org release) | https://doi.org/10.5281/zenodo.24138628 | `SwarmCore` |
  | ns3-tools (org release) | https://doi.org/10.5281/zenodo.24136068 | `ns3tools` |
  | Riley & Henderson 2010, the ns-3 paper | https://doi.org/10.1007/978-3-642-12331-3_2 | `RH10` |
  | Di Caro, Ducatelle & Gambardella 2004, AntHocNet (PPSN VIII) | https://doi.org/10.1007/978-3-540-30217-9_47 | `DDG04` |
  | Di Caro, Ducatelle & Gambardella 2005, AntHocNet (ETT) | https://doi.org/10.1002/ett.1062 | `DDG05` |
  | Güneş, Sorges & Bouazizi 2002, ARA | https://doi.org/10.1109/icppw.2002.1039715 | `G02` |
  | Roth 2005, Termite (PhD thesis) | https://hdl.handle.net/1813/240 | `R05` |
  | Roth & Wicker 2003, Termite (GLOBECOM) | https://doi.org/10.1109/glocom.2003.1258772 | `RW03` |
  | Schoonderwoerd et al. 1997, ABC | https://doi.org/10.1177/105971239700500203 | `S97` |
  | Wedde et al. 2005, BeeAdHoc (GECCO) | https://doi.org/10.1145/1068009.1068034 | `W05` |
  | Farooq & Wedde 2006, PG 460 report | https://doi.org/10.17877/de290r-14312 | `PG460` |
  | Zhao & Pan 2024, the LENS dataset | https://doi.org/10.1145/3625468.3652170 | `ZP24` |

  A new shared work or a new org release adds its row here, and an org
  release also its key in `zenodo.py`'s `ORG_KEYS` (its self-test compares the
  two).
- **Generated sections.** Once the file has an entry, org-sync renders
  CITATION.cff's `references:` and the README's Releases & citing list from its
  `implemented`, `tool` and `dataset` entries (an entry's `note` is its role
  line), in place of `[[references]]`, which it then reports as redundant: remove
  it in the same PR. An `@incollection` whose `booktitle` names proceedings, a
  conference, workshop or symposium, or whose `series` is a proceedings series
  (Lecture Notes in Computer Science: Crossref registers each LNCS paper as a
  book chapter), is a CFF `conference-paper` with `collection-type:
  proceedings`; any other stays `book` (#331). CITATION.cff is a seed, so a bib
  change reaches it through `python3 -I tools/org-sync/org_sync.py
  citation-refs REPO`, which rewrites only its `references:` block and leaves
  every other byte (`--check` reports drift and changes nothing); it works with
  or without `citation = true`, so a repository whose CITATION.cff is its own
  (AntHocNet) uses it too. A fidelity sheet's Sources table is `fidelity.py bib
  sources`'s, between its `fidelity:sources` markers.
- **Checked in CI.** `fidelity.py bib check` runs in the `org-sync` check
  (`reusable-org-sync-check.yml`) once `docs/references.bib` holds more than
  `%` comments (an entry, or text that is not one, which fails): the
  keys a sheet cites, the roles, a DOI or url per entry, the doi.org links, the
  repository's own DOI and any public line about where papers are kept. Once
  the bib has an entry and CITATION.cff exists, the same step runs
  `org_sync.py citation-refs --check`: CITATION.cff's `references:` that is not
  the bib's render fails it. The seed alone is not checked, so a repository
  turns it on with the PR that fills it.

### Archived releases

Read from Zenodo; the concept DOI resolves to the newest version.

| Repository | Concept DOI | Versions |
|---|---|---|
| AntHocNet | [10.5281/zenodo.20981979](https://doi.org/10.5281/zenodo.20981979) | every release to v2.6.1 (its CONTRIBUTING lists them) |
| ns3-swarm-core | [10.5281/zenodo.24138628](https://doi.org/10.5281/zenodo.24138628) | v0.1.0 [10.5281/zenodo.24138629](https://doi.org/10.5281/zenodo.24138629) |
| ns3-tools | [10.5281/zenodo.24136068](https://doi.org/10.5281/zenodo.24136068) | v0.1.0 [10.5281/zenodo.24136069](https://doi.org/10.5281/zenodo.24136069) |
| ARA | [10.5281/zenodo.24125198](https://doi.org/10.5281/zenodo.24125198) | v0.1.0 [10.5281/zenodo.24125199](https://doi.org/10.5281/zenodo.24125199) |
| BeeAdHoc | [10.5281/zenodo.24124821](https://doi.org/10.5281/zenodo.24124821) | v0.1.0 [10.5281/zenodo.24124822](https://doi.org/10.5281/zenodo.24124822) |
| Termite | [10.5281/zenodo.24124722](https://doi.org/10.5281/zenodo.24124722) | v0.1.0 [10.5281/zenodo.24124723](https://doi.org/10.5281/zenodo.24124723) |
| HOPNET | [10.5281/zenodo.24125265](https://doi.org/10.5281/zenodo.24125265) | v0.1.0 [10.5281/zenodo.24125266](https://doi.org/10.5281/zenodo.24125266) |
| benchmarks | [10.5281/zenodo.24145189](https://doi.org/10.5281/zenodo.24145189) | v0.1.0 [10.5281/zenodo.24145190](https://doi.org/10.5281/zenodo.24145190) (failed on the rate limit, archived from its tag by `zenodo.py create` on 2026-11-11, #226) |

### Cutting a release

**When to release** (maintainer decision 2026-11-11, on #216 and its
children). Every public repository releases, and Zenodo archives each release
(#216). There is no automatic, scheduled or per-change release. A version's
scope is the set of issues labelled `release:vX.Y.Z`, set when the issue is
opened or triaged (each repository's ladder, its `docs/roadmap.md`, or, for a
repository whose ladder has not landed yet, the ROADMAP's release train;
ROADMAP "Releases"). When that version's labelled issues are done, the maintainer, or
an agent on the maintainer's instruction, dispatches `bump`; an agent never
dispatches it on its own initiative. SemVer meaning: a minor for new features
(in `benchmarks`, new runs), a patch for fixes and docs, a major for a
breaking change (an API, wire-format, manifest or marker schema change). The
first release of every repository is `v0.1.0`. Commitizen bumps a patch only
from `fix:`, `refactor:` or `perf:` commits, so docs-only changes ride along with the
next release rather than making one of their own. While a repository is at 0.x,
Commitizen turns a breaking change into a minor (`major_version_zero`); a
major is a deliberate input of the release workflow (#211). After the release
is archived, read its concept DOI from Zenodo and set `zenodo_concept`,
reseed `CITATION.cff` and get the DOI badge (Releases and DOIs, above).

Every org repository releases through `reusable-release.yml` (#20); none
copies AntHocNet's `release.yml`. `main` takes no direct push (the `main`
rulesets require a pull request, and `GITHUB_TOKEN` cannot be a bypass
actor), so the bump goes through a PR and the tag follows the merge
(AntHocNet#789 option B, as AntHocNet#883 does for AntHocNet):

1. **Bump** (dispatch with mode `bump`). Commitizen computes the next version
   from the Conventional-Commit history since the last tag (`feat` → minor,
   `fix` → patch; a breaking change → minor while 0.x), rewrites the version
   files and writes `CHANGELOG.md`. A repository with no `v*` tag yet gets
   **v0.1.0** (ROADMAP "Releases"). A run with nothing that bumps (only
   `docs:`, `ci:`, …) fails, and nothing happens. The commit goes on the
   fixed branch `bot/release`, rebuilt on `main`'s tip, as the PR
   **`chore(release): bump version A to B`** (opened, or updated when one is
   open). It is pushed with the org GitHub App's token
   (`.github/actions/bot-token`: `BOT_APP_ID` / `BOT_APP_PRIVATE_KEY`, else
   `ORG_BOT_TOKEN`, else `GITHUB_TOKEN`), so CI runs on it. With
   `GITHUB_TOKEN` no CI starts, and the org's Actions policy
   (`can_approve_pull_request_reviews: false`, which also covers creating
   PRs) refuses the PR, so the App (or `ORG_BOT_TOKEN`) is needed. Nothing is tagged or published. If
   `main` moves before the merge, dispatch `bump` again.
2. **Merge the bump PR.** That is the release: the push to `main` runs the
   workflow, which releases only when the commit is the merge of a PR whose
   head is `<owner>/<repo>:bot/release` (`GET /repos/{repo}/commits/{sha}/pulls`)
   and its version is the one the PR's title names; any other push to `main`
   is a no-op.
3. **Build.** The caller's `build` command (default `make dist`) writes the
   assets of the merged commit into `dist/`, with `RELEASE_VERSION` and
   `RELEASE_TAG` set. It may test what it built; a failure stops the release.
   This job's token is read-only.
4. **Sign.** `SHA256SUMS`, a CycloneDX SBOM (`<repo>-<ver>.cdx.json`), signed
   SLSA build provenance for every asset as `<repo>-<ver>.intoto.jsonl`
   (Scorecard's Signed-Releases name) and as the Sigstore bundle
   `<repo>-<ver>.sigstore.json`, and an SBOM attestation. The verify commands
   of the notes then run on the runner: a release that does not verify never
   goes out.
5. **Publish.** The merged commit is tagged `v<ver>` (tags are outside the
   branch ruleset; the `release-tags` ruleset only stops a tag being moved or
   deleted). The org App's token (else `ORG_BOT_TOKEN`, else `GITHUB_TOKEN`)
   pushes the tag: GitHub refuses a new ref to `GITHUB_TOKEN`, which can never
   hold the `workflows` permission, when the tagged commit's
   `.github/workflows/` differs from the default branch's tip, as it does when
   `main` moved while the `release` environment waited for approval
   (ns3-tools v0.1.0). Then the GitHub release is created
   with every asset and notes holding the version's `CHANGELOG.md` section,
   the checksums and the verify commands. Zenodo then archives it (above:
   the integration's pull, or, with `zenodo: true`, the `zenodo` job's push).
   A re-run resumes: a tag already on this commit is kept and the release
   completed; a tag on another commit fails the run.

Mode `dry-run` bumps on the runner only, then builds, signs and verifies, and
stops: nothing is pushed, proposed, tagged or published, and its artifact
holds the release it would have published.

**A publish that fails, or waits.** Where a repository has the `release`
environment gate (Automation; off for now, #215, review #214), approving the
publish job is the maintainer's alone: an agent reports the waiting run and
never approves it. To recover a failed publish of a merged bump, re-run the
release run with **"Re-run all jobs"** (`gh api -X POST
repos/<owner>/<repo>/actions/runs/<id>/rerun`), never "Re-run failed jobs":
a partial re-run reuses the reusable workflow at the commit of the first
attempt, so a fix merged here since (ns3-tools#105, #209) would not apply.
The re-run keeps the bump's merge commit, rebuilds, re-attests and resumes;
a new `bump` dispatch is no substitute, since it would propose the version
again on another commit.

To adopt it, a repository adds a Commitizen config (in `pyproject.toml`, or
`.cz.toml` as in `tools/release/fixture/`):

```toml
[tool.commitizen]
name = "cz_conventional_commits"
version = "0.0.0"
version_scheme = "semver"
tag_format = "v$version"
major_version_zero = true
update_changelog_on_bump = true
version_files = ["VERSION"]   # every file that carries the version, e.g. "CITATION.cff:^version:"
```

a `make dist` target that writes its assets into `dist/`, and a workflow:

```yaml
name: Release
on:
  workflow_dispatch:
    inputs:
      mode:
        description: "dry-run: bump, build, attest and verify on the runner only; bump: open the bump PR (merging it releases)"
        type: choice
        options: [dry-run, bump]
        default: dry-run
  push:
    branches: [main]   # the merged bump PR releases; any other push is a no-op
permissions:
  contents: read
# One run per commit at a time, never cancelled (a later run must not replace
# a merged bump's pending release).
concurrency:
  group: release-${{ github.sha }}
  cancel-in-progress: false
jobs:
  release:
    # Saves a runner on ordinary pushes; the workflow itself checks the PR.
    # Quoted: the expression holds ': ', which YAML reads as a mapping in a plain scalar.
    if: "${{ github.event_name != 'push' || startsWith(github.event.head_commit.message, 'chore(release): bump version ') }}"
    permissions: { contents: write, pull-requests: write, id-token: write, attestations: write }
    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main
    with:
      mode: ${{ inputs.mode }}   # empty on push: release
    secrets:
      BOT_APP_ID: ${{ secrets.BOT_APP_ID }}
      BOT_APP_PRIVATE_KEY: ${{ secrets.BOT_APP_PRIVATE_KEY }}
      ORG_BOT_TOKEN: ${{ secrets.ORG_BOT_TOKEN }}
```

Run the dry run first. The publish job runs in the `release` environment,
which is ungated for now (maintainer decision 2026-11-11: set
`release_environment = false` in the repository's `[settings]`, Automation,
above); `release_environment = true` would make the maintainer approve each
publish. A repository that ships an
ns-3 module adds an `image` job after `release` that calls
`reusable-ns3-image.yml` with `tag: ${{ needs.release.outputs.tag }}` and
`if: ${{ needs.release.outputs.mode == 'release' }}` (Images, below; the
workflow's header has the snippet), so each release has both the module
tarball and the image. Users verify a download with:

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify <asset> --repo swarm-routing/<repo> \
  --signer-workflow swarm-routing/.github/.github/workflows/reusable-release.yml
gh attestation verify <asset> --repo swarm-routing/<repo> --predicate-type https://cyclonedx.org/bom \
  --signer-workflow swarm-routing/.github/.github/workflows/reusable-release.yml
```

Every check names the signer workflow: without `--signer-workflow`, `gh`
expects the signer in `--repo`, and the signer is this repository's
reusable workflow, not the caller's.

Inputs (a public contract, golden rule 10: they are only added, with
backward-compatible defaults): `build` (`make dist`), `dist-dir` (`dist`),
`working-directory` (`.`), `sbom-path` (`.`, the checkout at the release
commit), `dry-run` (`false`; `true` is mode `dry-run`), `mode` (empty:
`release` on a push, `bump` otherwise; or `bump`, `release`, `dry-run`).
Secrets (optional): `BOT_APP_ID`, `BOT_APP_PRIVATE_KEY`, `ORG_BOT_TOKEN`.
Outputs: `mode` (`bump`, `release`, `dry-run`, or `none` for a push that is
not a merged bump PR), `version`, `tag`, `artifact`, `pull-request` (bump
mode).

### Images

No repository builds its own ns-3 (#107). Every protocol image is built by
`reusable-ns3-image.yml` `FROM ghcr.io/swarm-routing/ns3-dev@sha256:…`: the
`ns3-dev:<version>-<profile>` tag is resolved to its digest once, the
repository's modules and their dependencies are built on that warm tree by
`ns3-build-contrib`, and their `test.py` suites run on the built image before
anything is pushed. Each image records its base in the label
`io.github.swarm-routing.ns3-dev.digest`, and its commit and every
dependency's commit in its other labels; it is signed (cosign keyless), with
build provenance and a CycloneDX SBOM. The workflow's header has the caller
examples and the verify commands (`cosign verify`, `gh attestation verify`).

- **Releases** publish `ghcr.io/swarm-routing/<repo>:<version>-<profile>`,
  `optimized` and `debug` by default: a caller names the package after its
  repository with `image: <repo>` (the input's default is still `<repo>-ns3`,
  #371; epic #370). Each release also moves the rolling `latest-<profile>`,
  and `latest` (its optimized image), to its digests, so a project can
  follow the newest release without a hash; a re-run of an older release
  never moves them back, and a pre-release never moves them (#373). If that
  step fails after the push, `tools/images/rolling_tags.py move --repo …
  --tag vX.Y.Z --profile <p> --verify-signature` repairs it from the version
  tag's digest, with no rebuild.
- **Campaigns** build one image per (commit, base digest),
  `<repo>-ns3-campaign:<commit7>-<base7>-<profile>` (the caller passes
  `tag: <commit7>-{base7}`), with `skip-existing: true`, so a second call with
  the same pair pushes nothing; every cell pulls it by digest. A campaign on a released version uses the release image.
- **Version tags never move.** A release tag that exists fails the build;
  only the `latest…` tags move. Anything that produces a published number
  pins a version tag or a digest, never `latest` (benchmarks rule 11). A
  campaign image is kept while any `swarm-routing/benchmarks` manifest names
  it.
- **Development images** live in a `<repo>-dev` package (a repository's
  campaign images: `anthocnet-dev`, `ns3-tools-dev`; epic #370) and are
  deleted after 2 days by a job of the owning repository's main pipeline
  that calls `reusable-dev-image-cleanup.yml` (`packages: <repo>-dev`, the
  job granted `packages: write`). A pinned image is never deleted:
  `tools/images/retention.py` keeps every version whose digest or tag a
  committed file names, on the default branch of any public org repository
  or the head of an open `swarm-routing/benchmarks` PR, as well as the
  package's newest image, its untagged versions and the signatures of the
  images it keeps (#371). Commit a campaign's plan, with its image digest,
  before dispatching it.

## Quality gates

The org's reusable workflows carry the checks; a repo turns them on in its
caller. Order of adoption and the decisions behind them: #35.

| Check | Where | Default |
|---|---|---|
| PR title is a Conventional Commit | `reusable-pr-title.yml` | on in every caller |
| clang-format (org `.clang-format`) | `reusable-ns3-ci.yml` `format` | on |
| Strict warnings as errors on the repo's own modules (ns-3 headers exempt) | `reusable-ns3-ci.yml` `strict-warnings` | off; turn on from a module's first PR |
| Determinism: same seed byte-identical, another seed differs (invariant 4) | `reusable-ns3-ci.yml` `determinism` | off; give it a short program with `{seed}` that prints its results (the marker lines) on stdout. Only stdout is compared: logging and sanitizer output on stderr are not results. A program that prints its seed (a `firstRun=` field, a run index) strips it with `determinism-normalize`, or the label alone would satisfy "seed 2 differs" |
| C++ coverage (gcovr), report-only | `reusable-ns3-ci.yml` `coverage` | off |
| SonarQube Cloud CI analysis (compile database + gcovr coverage of the repo's own modules) | `reusable-ns3-ci.yml` `sonar` + the org secret `SONAR_TOKEN`; the repo's `sonar-project.properties` (org-sync seed). A repo with Python passes `sonar-python-coverage: python-coverage` and makes the CI job `needs:` its `reusable-python-ci.yml` job in the same workflow, so the one analysis imports coverage.py's report too (SonarQube Cloud keeps one analysis per branch) | off; skipped on fork PRs and while the project is on Automatic Analysis |
| Codecov upload of that coverage, report-only (PR comment, badge) | `reusable-codecov.yml` in a job `needs: ci` with `id-token: write` (GitHub OIDC; no Codecov token is stored); the repo's `.codecov.yml` (org-sync seed). It uploads the `coverage` artifact, so the CI job needs `coverage` or `sonar` on and the `debug` profile | off; an upload failure, or no artifact, never fails CI |
| Container lint and scans: hadolint, Trivy config and image reports to code scanning | `ns3-containers` `container-security.yml`, `publish-images.yml` | on there |
| ruff check + format (org `ruff.toml`) and Python coverage, report-only | `reusable-python-ci.yml` | on in every caller |
| OpenSSF Scorecard, report-only: score published to the OpenSSF API (badge) and SARIF to code scanning | `reusable-scorecard.yml`, called by org-sync's `.github/workflows/scorecard.yml` (weekly, on push to `main`, on demand) | on in every public repo; a private one lists the workflow in `skip` |

Coverage has no threshold: read it as a map of untested paths (AntHocNet #162).
A floor, if ever, is chosen from evidence in its own issue. Codecov's statuses
(project: no drop over 1%, patch: 80%) are information, not a required check.
SonarQube Cloud and Codecov were adopted on 2026-11-09 (#35, #24). A C++ repo
switches its SonarQube Cloud project to CI-based analysis (Administration >
Analysis Method) when it turns `sonar` on: Automatic Analysis cannot import
coverage, and the two cannot run together. Their badges come from org-sync
(`sonar`, `codecov`, `coderabbit` in `badges`; `[quality] sonar = false` in
`org-sync.toml` for a repository with no SonarQube Cloud project yet); the org profile shows each
repository's quality gate and coverage.

OpenSSF Scorecard (#23) runs from the reusable workflow, not a copy per repo:
the Scorecard API accepts a published result only from a workflow that keeps
its [restrictions](https://github.com/ossf/scorecard-action#workflow-restrictions),
and it checks the called workflow (the one holding the `ossf/scorecard-action`
step), so `reusable-scorecard.yml` keeps them: no top-level `env` or
`defaults`, no workflow-level write permission, `id-token: write` on the
Scorecard job only, a literal Ubuntu runner, and only `uses:` steps from the
approved actions. The caller's job grants `security-events: write` and
`id-token: write`. The `scorecard` badge (org-sync) appears with the workflow,
and the first push to `main` after it lands publishes the first score. A low
score is a finding to triage in an issue, not a build break. Whether a repo
also fills the CII Best Practices questionnaire is decided per repo on #23.

## AI agents

Every repo carries an `AGENTS.md` (what the repo is, build & verify, golden
rules, conventions, the org's working defaults, session habits, response style
and agent pitfalls, where to look), in the shape of AntHocNet's, and a
`CLAUDE.md` that is the single line `@AGENTS.md` and nothing else (#277): Claude
Code reads `CLAUDE.md`, every other agent reads `AGENTS.md`, and each rule is
written once. `CLAUDE.md` is an org-managed file, so text added to it is drift;
anything a repository wants an agent to know goes in its `AGENTS.md`. Change a convention here and in each repo's `AGENTS.md` together.
