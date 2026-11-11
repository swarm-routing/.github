# Contributing to swarm-routing

Org-wide defaults. A repository's own `CONTRIBUTING.md` overrides this file.
Participation follows the org's default [Code of Conduct](CODE_OF_CONDUCT.md);
where to ask is in the org's default [SUPPORT.md](SUPPORT.md). A repository's
own `CODE_OF_CONDUCT.md` or `SUPPORT.md`, where it has one, takes precedence.
These conventions come from [`danieljoppi/AntHocNet`](https://github.com/danieljoppi/AntHocNet),
the source repository the org was split out of; its
[ADR-0013](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)
is the long form.

## Invariants (every repo)

1. **Licensing per directory, as AntHocNet** ([LICENSING.md](https://github.com/danieljoppi/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)).
   A simulator-free `core/` and the standalone tooling (`tools/`, Python CLIs,
   CI and image scripts) are `MIT OR GPL-2.0-only`; ns-3 modules, the site,
   docs and data are `GPL-2.0-only`. Each repo carries `LICENSE` (GPL-2.0),
   `LICENSE-MIT` and a `LICENSING.md` map. Every original `.h`, `.hpp`, `.cc`,
   `.cpp`, `.py`, `.sh` starts with
   ```cpp
   // Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
   // SPDX-License-Identifier: MIT OR GPL-2.0-only   (or GPL-2.0-only)
   ```
   (`#` comments for Python and shell). The dependency goes one way: GPL code
   may use the dual parts, never the reverse — a `core/` file includes only the
   C++ standard library, other `core/` files and the dual-licensed core of a
   declared dependency (a protocol's `core/` on swarm-core's `core/`, the
   `core-deps` input of whichever workflow runs the licence check: `licence.yml`
   calling `reusable-licence-check.yml`, or `ci.yml` calling
   `reusable-ns3-ci.yml`, which forwards it). CI
   (`reusable-licence-check.yml`, `tools/checks/check-headers.py`) enforces all
   of it. Contributions are accepted under the licence of the directory they
   land in. Write clean implementations against public ns-3 interfaces rather
   than copying from ns-3's `src/aodv`, `src/olsr` & co.; third-party code keeps
   its own licence and lands only with its provenance recorded.
2. **POD wire messages.** Control headers are simulator-independent POD structs
   with bounds-checked little-endian readers/writers, a leading version byte, and
   deterministic roundtrip + fuzz tests.
3. **No module named `core`.** It collides with ns-3's `src/core`; the shared
   module is `swarm-core` (`#include "ns3/swarm-core-module.h"`).
   `ns3-build-contrib` refuses the name.
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
   (`step-security/harden-runner`, pinned by SHA, #164): it records each
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
repositories (such as `papers`) never appear. Whoever changes an epic (opens,
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
repository; private repositories such as `papers` run no pipelines and no
automatic CodeRabbit review, so a new label is added there by hand):

| Kind | Rule | Labels |
|---|---|---|
| Type | exactly one; umbrellas add `epic` | `bug`, `enhancement`, `chore`, `documentation`, `verification` (+ `question`, `handoff`) |
| Area | one or more | `protocol`, `adapter`, `ns3`, `benchmark`, `observability`, `packaging`, `learn-site`, `literature` |
| Model | exactly one: what a wrong first pass costs, not code volume | `model:haiku-4.5` (mechanical), `model:sonnet-5` (plumbing, tooling, docs), `model:opus-4.8` (protocol semantics, root cause, CI-validated adapter work), `model:fable-5` (architecture, greenfield) |
| Priority | exactly one on non-epic issues | `priority:P1` (regression / invalidates numbers), `priority:P2` (gates a result or feature), `priority:P3` (valuable, not blocking) |
| Release | only when a roadmap gates the issue | `release:vX.Y.Z` |
| Contributor | any number, set by a maintainer when an outside contributor can pick the issue up | `good first issue` (small, well scoped, needs no history), `help wanted` (outside help welcome) |

GitHub lists open `good first issue` issues on each repository's Contribute
page (`/contribute`); `help wanted` issues are found through the label filter
(`/issues?q=is:open+label:"help wanted"`). Either says in its body what a
newcomer needs (files, the check that proves it, the repository's
`AGENTS.md` build commands).

`migrated` marks an issue cloned from `danieljoppi/AntHocNet` during the split;
its body starts with *Migrated from `danieljoppi/AntHocNet#N`*.

**Handoffs are issues** (template *Handoff*, label `handoff`). A new session
starts from the newest open `handoff` issue and closes it when done.

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
  the PR to the queue (the merge button, or auto-merge), and the queue tests
  it on top of `main` and the PRs ahead of it, then merges it. Every workflow
  that produces a required check runs `on: merge_group` there; the reusable
  PR-title check skips itself on a merge group (a skipped check passes) and
  the org-sync check judges the group's own change against its base.
- **`main` takes no direct push** in any repo: the `main` ruleset requires a
  PR, an up-to-date branch and the required checks. Bots push `bot/<name>`
  branches and open PRs; releases go through the bump PR (Cutting a release).
- Where there is no queue yet: when a PR falls behind `main`, update it and
  merge PRs one at a time, each after its CI on the updated branch.
  `tools/pr-status/pr_status.py merge
  REPO#N [REPO#N …]` does exactly that: in the order given (repositories
  independently), it updates a PR GitHub reports `behind`
  (`PUT pulls/<n>/update-branch`), waits for every check on the new head,
  squash-merges with the title `<PR title> (#n)`, and only then moves on to
  that repository's next PR. It never merges while a required check is
  missing on the head, and stops and reports on a failing check (a workflow
  that ended in `startup_failure` counts as one), an unresolved review thread, a conflict, a draft or a refusal, and never
  reruns a check or resolves a thread itself (`--dry-run` says what it would
  do). Never force-push a branch someone else pushed. A behind `bot/release` PR is the exception:
  dispatch `bump` again (Cutting a release).
- `Closes #N` in a PR body closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.

## Automation

Two scheduled workflows in this repository keep the org current. Both are dry
runs until their secret is set, and the secrets belong to the maintainer:

| Workflow | What it does | Secret |
|---|---|---|
| `org-bot` (daily, and on every push that changes `templates/` or a generator) | Opens one PR per repository when its `## Epics` section (and, here, ROADMAP.md and the profile) or its org-managed files have drifted. The same change is never proposed twice; an older bot PR is closed as superseded. It never merges | The org GitHub App (`BOT_APP_ID`, `BOT_APP_PRIVATE_KEY`; below), else `ORG_BOT_TOKEN`: a fine-grained token on the org, all repositories, with Contents, Pull requests and Workflows read and write |
| `zenodo` (daily) | See Releases and DOIs below | `ZENODO_TOKEN` |
| `repo-settings` (daily check; apply on every push that changes `templates/rulesets/` or the tool) | Keeps each repository's settings equal to the `[settings]` table of its `.github/org-sync.toml` and its profile in `templates/rulesets/` (`tools/repo-settings/repo_settings.py`): description, homepage, topics; merge settings (squash only, PR title and body as the commit, delete the branch, auto-merge allowed, always suggest updating PR branches) and features (issues on; wiki, projects, discussions off); the `main` ruleset and the `release-tags` ruleset (v* tags cannot be deleted, force-pushed or moved); security features, only ever turned on (Dependabot alerts and security updates, secret scanning and push protection, private vulnerability reporting, CodeQL default setup except where the repository runs its own CodeQL workflow; on a private repository the free plan offers only the Dependabot ones, the rest is reported unsupported); the Actions policy (selected actions: GitHub's own plus the list in `templates/rulesets/defaults.json`, `GITHUB_TOKEN` read-only by default, Actions may not approve PRs); and, where enabled, a `release` environment with the maintainer as required reviewer. The daily check opens, updates or closes one `[settings]` drift issue; a private repository's values are never printed. It never deletes a ruleset or an environment, never turns a security feature off, and only manages the rulesets named in its profiles | The org GitHub App, else `ORG_BOT_TOKEN` (a fine-grained token). Either needs, on every repository, besides org-bot's: **Administration: read and write** (every settings write, and reading rulesets, security and Actions settings), **Contents: read** (each `org-sync.toml` and the workflows), **Actions: read** (the `release` environment), Metadata: read. No Dependabot alerts, Secret scanning alerts or Code scanning alerts permission is needed: those cover the alerts, not the settings. The App already has Administration: write; check it also has the reads. Until the token has them, apply reports `refused` (or `unreadable`) and only the check runs |

Each adopting repository's `org-sync` check (`reusable-org-sync-check.yml`)
judges a PR by its own change only (#159): on `pull_request` it runs
`org_sync.py check --changed-only` against the PR's base, so it fails only when
the PR changes a managed file (or deletes a seed) or touches a line inside a
managed section. A template change here therefore never turns red the open PRs
that touch no managed file; they merge as they are, and org-bot's refresh PR
brings the templates in. A push to `main` keeps the full check, so drift there
stays visible until the refresh PR merges. A caller that wants the full check on
PRs too passes `full-check-on-pr: true`.

Settings are changed by PR, never by hand: edit the repository's `[settings]` (or a profile here) and the next apply writes it (a profile change applies on push here; a `[settings]` change in another repository applies when `repo-settings` is dispatched with mode `apply` after its merge); a hand edit, in the UI or by a direct API write, shows up as drift the next day. A required check must run on every PR (no `paths:` filter; skip the work inside a gate job instead), or the PRs it skips can never merge, and its name must match the check run's name exactly. An org-level ruleset (an org-owner setting) can add a floor every repository inherits, including new ones before their `[settings]` land.

A repository's `[settings]` can override what its profile gives it: `features = { has_wiki = true }` (any of `has_issues`, `has_projects`, `has_wiki`, `has_discussions`, `allow_auto_merge`, `allow_update_branch`), `security = { codeql_default_setup = false }` (false leaves that feature alone; it is never turned off), and `release_environment = true`. `merge_queue = true` adds a merge queue to the `main` ruleset (squash; every PR of a group must pass, `ALLGREEN`; groups of 1 to 5 PRs, checks running for at most 5 queued PRs at once; 120 minutes for the required checks; `MERGE_QUEUE` in the tool); a table such as `merge_queue = { check_response_timeout_minutes = 60 }` overrides any of them, within the API's bounds. It needs `required_checks`, GitHub offers it only on public organization repositories, and every workflow that produces a required check must also run `on: merge_group` (with a path filter or a `changes` job, diff against `github.event.merge_group.base_sha`, since a merge group has no `pull_request`), or the queue waits for a check that never comes: `repo-settings` refuses the repository, before writing anything, while a workflow that runs on `pull_request` and has a job named (or with the id) a required check's first ` / ` segment lacks that trigger (a `${{ … }}` in a job name, as in a matrix, matches any text; reusable `workflow_call`-only workflows are not counted). The Actions policy allows only the actions listed in `templates/rulesets/defaults.json` (`selected_actions.patterns_allowed`, besides GitHub's own and local ones): a workflow that starts using a new third-party action needs its `owner/repo@*` added there in the same change (in another repository: merged here first), or `repo-settings` refuses that repository (the check names the action) rather than switching it to a policy that would break its CI. The `release` environment (required reviewer: the maintainer) is created only where `release_environment = true`; no repository enables it yet: turn it on in a repository when it adopts the reusable release workflow (#116) and that workflow's job names `environment: release`. The `release-tags` ruleset does not restrict who creates a v* tag: the release workflows push tags with `GITHUB_TOKEN`, which cannot be a ruleset bypass actor, so a creation rule would block every release.

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

### Cutting a release

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
   deleted, so `GITHUB_TOKEN` pushes it), and the GitHub release is created
   with every asset and notes holding the version's `CHANGELOG.md` section,
   the checksums and the verify commands. Zenodo then archives it (above). A
   re-run resumes: a tag already on this commit is kept and the release
   completed; a tag on another commit fails the run.

Mode `dry-run` bumps on the runner only, then builds, signs and verifies, and
stops: nothing is pushed, proposed, tagged or published, and its artifact
holds the release it would have published.

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
    if: ${{ github.event_name != 'push' || startsWith(github.event.head_commit.message, 'chore(release): bump version ') }}
    permissions: { contents: write, pull-requests: write, id-token: write, attestations: write }
    uses: swarm-routing/.github/.github/workflows/reusable-release.yml@main
    with:
      mode: ${{ inputs.mode }}   # empty on push: release
    secrets:
      BOT_APP_ID: ${{ secrets.BOT_APP_ID }}
      BOT_APP_PRIVATE_KEY: ${{ secrets.BOT_APP_PRIVATE_KEY }}
      ORG_BOT_TOKEN: ${{ secrets.ORG_BOT_TOKEN }}
```

Run the dry run first. The publish job runs in the `release` environment:
set `release_environment = true` in the repository's `[settings]`
(Automation, above) so the maintainer approves it. A repository that ships an
ns-3 module adds an `image` job after `release` that calls
`reusable-ns3-image.yml` with `tag: ${{ needs.release.outputs.tag }}` and
`if: ${{ needs.release.outputs.mode == 'release' }}` (Images, below; the
workflow's header has the snippet), so each release has both the module
tarball and the image. Users verify a download with:

```bash
sha256sum -c SHA256SUMS --ignore-missing
gh attestation verify <asset> --repo swarm-routing/<repo> \
  --signer-workflow swarm-routing/.github/.github/workflows/reusable-release.yml
gh attestation verify <asset> --repo swarm-routing/<repo> --predicate-type https://cyclonedx.org/bom
```

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

- **Releases** publish `ghcr.io/swarm-routing/<repo>-ns3:<version>-<profile>`,
  `optimized` and `debug` by default.
- **Campaigns** build one image per (commit, base digest),
  `<repo>-ns3-campaign:<commit7>-<base7>-<profile>` (the caller passes
  `tag: <commit7>-{base7}`), with `skip-existing: true`, so a second call with
  the same pair pushes nothing; every cell pulls it by digest. A campaign on a released version uses the release image.
- **Tags never move.** A release tag that exists fails the build. A campaign
  image is kept while any `swarm-routing/benchmarks` manifest names it.

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

## AI agents

Every repo carries a `CLAUDE.md` (imports `AGENTS.md`; working defaults,
response style, handoffs as issues) and an `AGENTS.md` (what the repo is,
build & verify, golden rules, conventions, where to look), in the shape of
AntHocNet's. Change a convention here and in each repo's `AGENTS.md` together.
