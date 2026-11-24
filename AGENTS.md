# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/.github`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/swarm-routing/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

Org-wide defaults for every `swarm-routing` repository: the profile page,
default issue forms and PR template, the label taxonomy, the C++ style, and the
reusable workflows other repos call (`reusable-ns3-ci.yml`, `reusable-ns3-image.yml`,
`reusable-release.yml`, `reusable-benchmark-cell.yml`, `reusable-python-ci.yml`,
`reusable-go-ci.yml`, `reusable-doxygen.yml`, `sync-labels.yml`). Pipelines (code a workflow runs) are
written in Go, skill scripts stay Python ([ADR-0002](docs/adr/0002-pipelines-are-go.md),
CONTRIBUTING § Languages; the existing Python tools move one at a time, #531).
Files here only take effect from `main` (GitHub reads community defaults from
the default branch; callers reach a reusable workflow change once org-bot's
refresh PR moves their pinned commit, ADR-0004).

```
profile/README.md, ROADMAP.md, CONTRIBUTING.md   the org landing page, its phases, its invariants and conventions
ISSUE_TEMPLATE/, pull_request_template.md, labels.json   the default forms and the label taxonomy
SECURITY.md, CODE_OF_CONDUCT.md, SUPPORT.md, DCO, .github/FUNDING.yml   the org default community files
.clang-format, ruff.toml           the C++ style and the Python lint baseline
.clang-tidy                        the clang-tidy checks the protocol cores' `core` check runs, findings as errors (#635)
go.mod, cmd/<tool>/, internal/, docker/ci-tools/   the Go pipeline tools and the ci-tools image (ADR-0002)
tools/<tool>/                       the org's scripts, each with --self-test (checks, org-sync, org-bot, epics, zenodo, docs-review, fidelity, protocol-review, pr-status, lit-search, repo-settings, release)
templates/                          what org-sync renders into each repository; templates/rulesets/: the settings profiles
.github/workflows/, .github/actions/   the reusable workflows other repos call, this repo's CI and bots, the bot token
docs/                               tools.md (every file, tool, workflow and self-test), where-to-look.md (the full task table), adr/ (the org's decisions)
```

Before adding, changing or running a tool or a workflow, read
[`docs/tools.md`](docs/tools.md): one line per file and directory, every
self-test and read-only run, and how a reusable workflow change is proven.

## Build & verify

The step-by-step version for people (prerequisites, every command, the CI
map, troubleshooting) is [`docs/development.md`](docs/development.md).

No build. Before pushing:

```bash
pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1   # once, as ci.yml
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
tools/checks/check-headers.sh --self-test && tools/checks/check-headers.sh --dual '' .   # the Go gate: docker, or go
# and the --self-test of every tool you changed: the exact commands are in docs/tools.md
pip install "ruff==$(sed -n 's/^RUFF_VERSION=//p' tools/versions.env)" && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml; tools/doctor/doctor.sh . compares every tool with CI
```

Every tool has a `--self-test` against fixtures or a fake GitHub, and most a
read-only run against the real org; [`docs/tools.md`](docs/tools.md#self-tests-and-read-only-runs)
lists each with what it covers. A change to a reusable workflow is proven by
its self-test workflow and then by a caller: read
[`docs/tools.md`](docs/tools.md#validating-a-change-to-a-reusable-workflow)
before changing one.

## Golden rules (invariants — do not break)

Org-wide (1–9), then this repo's own.

1. **Licensing per directory, as AntHocNet** ([`LICENSING.md`](LICENSING.md);
   AntHocNet [LICENSING.md](https://github.com/swarm-routing/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)). A
   simulator-free `core/` and the standalone tooling are `MIT OR GPL-2.0-only`;
   ns-3 modules, the site, docs and data are `GPL-2.0-only`. Every original
   `.h`/`.hpp`/`.cc`/`.cpp`/`.go`/`.py`/`.sh` starts with
   `// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)` +
   `// SPDX-License-Identifier: <MIT OR GPL-2.0-only | GPL-2.0-only>` (`#`
   comments where needed), matching its directory in `LICENSING.md`; an
   outside contributor may add their own `Copyright (c) <year> <Name>` line
   beneath the org line, never replace it, and signs off every commit (DCO,
   CONTRIBUTING "Outside contributions"). CI (`reusable-licence-check.yml`)
   checks the SPDX line, and the org line's place when a header names more
   than one holder; a header with a single, other holder (a replaced org line,
   or third-party code) passes it, so review catches that. A new directory
   gets its row in `LICENSING.md` in the same PR.
2. **The licence boundary only goes one way.** GPL code may use the dual
   parts; dual code never pulls GPL-only code in: a `core/` file includes only
   the C++ standard library, other `core/` files and the dual-licensed `core/`
   of a dependency pinned by commit and declared as the `core-deps` input of
   every workflow that runs the licence check (one calling
   `reusable-licence-check.yml`, or one calling `reusable-ns3-ci.yml`, which
   forwards it; workflow file names differ per repo), each with the same pin,
   with `core-roots` naming the repo's own `core/`
   (without it the check skips core includes; a protocol's `core/` on
   swarm-core's; CI checks it, `check-headers --core-dep`), and a dual script imports no GPL-only code. Code coming from AntHocNet keeps its
   licence: its `core/`/`tools/` (dual) may land in dual or GPL paths here; its
   `ns3/` modules and `web/` (GPL-2.0-only) only in GPL paths. Third-party code
   (AntHocNet's vendored `aomdv`/`gpsr`, IITP RAS) lands only in GPL paths with
   its provenance recorded. Write clean implementations against public ns-3
   interfaces rather than copying ns-3's `src/aodv`/`src/olsr`.
3. **Wire formats are POD + versioned.** Control headers are
   simulator-independent POD structs with bounds-checked little-endian
   readers/writers, a leading version byte, and deterministic roundtrip + fuzz
   tests. Changing a field or its units bumps the version byte.
4. **No contrib module named `core`** (collides with ns-3's `src/core`). The
   shared module is `swarm-core` (`#include "ns3/swarm-core-module.h"`), and
   every protocol builds on it, AntHocNet included: `core/` on its `core/`, the
   ns-3 adapter on `SwarmRoutingBase` (swarm-routing/swarm-adapter-ns3#14).
5. **Determinism.** A fixed `--seed=<N>` gives byte-identical output. All
   randomness through the simulator's seeded streams or an injected RNG port;
   never libc `rand()`, wall-clock time, or unordered-container iteration order
   in anything that reaches an output.
6. **Comparisons are paired.** Per-seed deltas across >= 20 seeds, emitting the
   canonical `##CONFIG##`, `##RUN##`, `##BENCH##`, `##DIAG##` lines. A
   comparator arm (a protocol we did not design) counts only after its three
   gates: a fidelity sheet from its paper, the per-PR delivery smoke, and an
   anchor reproducing the paper's own trend.
7. **Keep bounded structures bounded** (visited paths, dedup histories, queues
   carry a configured cap).
8. **CI hygiene.** Actions pinned by full commit SHA with a `# vX.Y.Z` comment;
   buildx caches scoped per profile; transient artifacts `retention-days` <= 7.
   Every job that runs steps has a `timeout-minutes` cap (a job that only
   calls a reusable workflow cannot take one: the called workflow's jobs carry it), and every apt, npm or installer step
   its own, sized from recent green runs; `apt-get update` runs with
   `--error-on=any` inside a shell retry. Ubuntu mirror outages are the usual
   cause of a red run.
9. **Nothing shipped depends on `.claude/`.** Skills hold procedures; scripts
   that anything shipped needs live in `tools/` (AntHocNet ADR-0014).
10. **Reusable workflows are a public contract.** Callers pin them by commit: every `uses: swarm-routing/.github/...` names the commit the caller's `.github/org-sync.lock` pins (`@<sha> # main@<date>`), and org-bot's org-sync refresh PR moves the lock and every reference together; `check / org-sync` fails on any other ref, `@main` included ([ADR-0004](docs/adr/0004-callers-pin-the-org-workflows-by-commit.md), #716; amended 2026-11-22, was "callers pin `@main`"). Inside this repository a top-level workflow calls `./.github/workflows/...`; a reusable workflow calls this repository's actions and workflows pinned too (`org_sync.py refs`). Never rename or remove an input, never change a default's meaning; add inputs with backward-compatible defaults. A breaking change needs a new file or a tag, announced in an issue in every caller repo.
11. **`labels.json` is the taxonomy.** Change it together with `CONTRIBUTING.md` and the issue forms; `sync-labels` never deletes labels, nor does the `labels` workflow that applies it to every repository on change, so a rename is a manual migration recorded in an issue.
12. **The issue forms stay AntHocNet's shape.** Same fields, same body sections; org-specific additions only (areas, Depends on, literature).

## Conventions

- Issues follow the org taxonomy ([CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#issues), from
  [AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)): one type label
  (`bug`/`enhancement`/`chore`/`documentation`/`verification`, plus `epic` for
  umbrellas), area label(s) (`protocol`/`adapter`/`ns3`/`benchmark`/
  `observability`/`packaging`/`ci`/`learn-site`/`literature`), one `model:*`
  suggestion (a model on the Claude Pro plan), one `priority:P1|P2|P3` on
  non-epic issues (none on an epic), and a `release:vX.Y.Z` label only when
  a release in the repository's ladder (`docs/roadmap.md`, else the org
  ROADMAP's release train) gates the issue: that label set is the version's
  scope, released when its issues are done (CONTRIBUTING "Cutting a
  release"). Labels come from `.github`'s `labels.json`, applied to every
  repository as soon as it changes (never deleting one); a release version
  it lacks is added there (and to CONTRIBUTING's label table), or, in a
  repository that keeps its own release labels (AntHocNet), created with
  `gh label create release:vX.Y.Z`.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Epics are listed in a public repository's README `## Epics` and the org
  [ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics),
  generated from the `epic` issues by `.github`'s `tools/epics/epics.py`. An
  open epic is Planned (no sub-issue closed) or In progress (some closed); it
  is Done or Dropped only once the epic itself is closed (completed or not
  planned). The lists follow the issues with no hand step: an issue change
  that can move them makes the org-managed `epics-changed.yml` run org-bot's
  `epics` task, which opens the refresh PRs. Never edit a generated section
  by hand; private repositories keep none.

## Git workflow

- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`: a lowercase Conventional Commit, `type(scope)!:
  subject`, type one of `feat fix docs style refactor perf test build ci
  chore revert`, subject starting lowercase.
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR and
  the required checks, not an up-to-date branch. Bots push `bot/<name>`
  branches and open PRs; a release is the bump PR from `bot/release`, tagged
  after it merges (CONTRIBUTING "Cutting a release").
- A PR behind `main` may merge as it is. Update it
  (`gh api -X PUT "repos/<owner>/<repo>/pulls/<n>/update-branch"`, the PR's
  base repository) only when `main` changed what it touches (a template, a
  workflow, a required check), then merge after its CI. Never update a
  merge-queue PR by hand: enable auto-merge and the queue tests it on the
  latest `main` (CONTRIBUTING "Merge when CI is green"). Never force-push a
  branch someone else pushed. A behind `bot/release` PR: dispatch the release
  `bump` again.
- **Settings are code.** Settings, rulesets, required checks and the Actions
  allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in
  `swarm-routing/.github`, never in the UI or by a direct API write. A
  rulesets change applies on merge, a `[settings]` change on its push through
  the org-managed `settings-apply.yml` (swarm-routing/.github#569). A required
  check runs on every PR (no `paths:` filter; skip work inside a gate job) and
  is named exactly as its check run. A new third-party action goes into
  `defaults.json` `selected_actions` (`templates/rulesets/`) in swarm-routing/.github
  before or with the workflow that uses it, or `repo-settings` refuses the repo.

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
- Search an output the harness saved to a file (`grep`, `head`, `sed -n`),
  never read it whole; wait on a PR with `pr_status.py wait` or `wait
  --merged`, not by subscribing to its activity (swarm-routing/.github#794).
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

## Where to look

One line per task. Each row has a full entry in [`docs/where-to-look.md`](docs/where-to-look.md)
(the commands, the configuration, the issues behind it): read it before
changing what the row names.

| You want to… | Go to |
|--------------|-------|
| Change the CI every protocol repo runs | `.github/workflows/reusable-ns3-ci.yml` |
| Build a protocol's release or campaign image | `.github/workflows/reusable-ns3-image.yml` |
| Run one benchmark cell of any protocol repository | `.github/workflows/reusable-benchmark-cell.yml` |
| Publish a C++ core as a vcpkg port, or consume one from outside the org | swarm-routing/vcpkg-registry; `reusable-release.yml` input `vcpkg-ports`; CONTRIBUTING "Dependencies" |
| Cut a release of any org repository, or change how releases are made | `.github/workflows/reusable-release.yml` |
| Turn on SonarQube Cloud or Codecov for a C++ repo | `reusable-ns3-ci.yml` input `sonar`, `reusable-codecov.yml`, `templates/quality/` |
| Build a C++ repository's class documentation (Doxygen) | `reusable-doxygen.yml`, `templates/workflows/api-docs.yml`, `templates/api/Doxyfile.in` |
| Change the Python lint/coverage or the PR-title rule | `reusable-python-ci.yml` + `ruff.toml`; `reusable-pr-title.yml` |
| Choose a language, or write a Go pipeline tool and its CI | `docs/adr/0002-pipelines-are-go.md`, CONTRIBUTING § Languages, `reusable-go-ci.yml`; migration epic #531 |
| Add a Go tool or run one from a workflow (the `ci-tools` image) | `cmd/<tool>/`, `internal/`, `docker/ci-tools/Dockerfile`, `ci-tools-image.yml`; `docker run --user … -v …:ro ghcr.io/swarm-routing/ci-tools@sha256:… <tool>` in a `run:` step, never `uses: docker://` (ADR-0002) |
| Change the licence rules or their gate | `cmd/check-headers` (Go; run locally by `tools/checks/check-headers.sh`), `reusable-licence-check.yml`, CONTRIBUTING rule 1 |
| Change how outside contributions are accepted (DCO, contributor copyright lines) | CONTRIBUTING "Outside contributions", `tools/checks/check-dco.py`, `reusable-dco.yml` |
| Add or rename a label | `labels.json` + `CONTRIBUTING.md` + `ISSUE_TEMPLATE/` |
| List an org skill in every repo's AGENTS.md | `templates/agents/skills.md` |
| Change what every repo shares (org sections, badges, SECURITY, ADR template, Makefile) | `templates/` + `tools/org-sync/org_sync.py`; each repo is checked at the commit its `.github/org-sync.lock` pins, so a template change turns nothing red: org-bot's refresh PR moves the pin and the text together (#586) |
| Bring a repo onto the templates | `tools/org-sync/org_sync.py init` (new repo) or `plan` → `apply` → `check` |
| Change the org security policy | `SECURITY.md`, `templates/SECURITY.md.in`; write no claim a repo cannot back |
| Record an ns-3 bug, or look one up (RCAPA) | swarm-routing/sim-tools `docs/ns3-bugs.md`, `docs/ns3-rcapa/`; form `ISSUE_TEMPLATE/rcapa.yml` |
| Record a regression in a published library (RCAPA), or change the rule | CONTRIBUTING "RCAPA", ADR-0003, `templates/rcapa/` (seeded into each repo's `docs/rcapa/`), form `ISSUE_TEMPLATE/rcapa-regression.yml` |
| Change the C++ style | `.clang-format` |
| Change the org landing page | `profile/README.md` |
| Give a workflow the bot's token, or check the org App's permissions | `.github/actions/bot-token`; CONTRIBUTING "The bot's GitHub App" |
| Keep epic lists, org-managed files and protocol repositories' swarm-core pins current without hand PRs | `tools/org-bot/org_bot.py`, `org-bot.yml` |
| Change how security alerts are ticketed or fixed (the tickets, the SLA, the agent, its rules, the guard) | `cmd/security-alerts`, `reusable-security-autofix.yml`, `templates/security-autofix/prompt.md`, `cmd/security-autofix`; CONTRIBUTING "Security alerts" (#629) |
| Check that every release is on Zenodo, or archive a missed one | `tools/zenodo/zenodo.py`, `zenodo.yml` |
| Register a repository for the OpenSSF Best Practices badge, or check its entry | `cmd/bestpractices` (Go), `bestpractices.yml`, org-bot task `bestpractices` |
| Hold a repo's README, AI files and docs/ to the org standard | `tools/docs-review/check_docs.py`, `ai_files_review.py`, `ai-files-review.yml` |
| Check a diff against the org golden rules before review | `tools/protocol-review/check_invariants.py` |
| See open PRs' CI and review threads, wait for CI, or merge PRs that fall behind | `tools/pr-status/pr_status.py` |
| Confirm a reference, or find newer, citing, cited or related papers | `tools/lit-search/lit_search.py` |
| Change a repository's settings, rulesets, required checks, merge queue or Actions policy | its `.github/org-sync.toml` `[settings]`, `templates/rulesets/`, `tools/repo-settings/repo_settings.py` |
| Write or check a protocol's paper-fidelity sheet | `tools/fidelity/fidelity.py` |
| List, or refresh, the epics (README sections, ROADMAP, profile) | `tools/epics/epics.py`, `epics.yml` |
| See or change the org Project (a generated, read-only view; the files and labels are the record) | `templates/projects/plan.json`, `cmd/project-sync`; CONTRIBUTING "Where the plan lives" (#541) |
| Know where the org is going beyond ns-3, and which decisions wait on the maintainer | `ROADMAP.md` "Architecture and migration"; epics #672, #674, #252, #272 |
| Make the agent files shorter, or the org's state readable by a new session | #277, #278, #281 under epic #141 |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`swarm-routing/AntHocNet`](https://github.com/swarm-routing/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
