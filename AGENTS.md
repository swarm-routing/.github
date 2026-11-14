# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/.github`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/swarm-routing/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

Org-wide defaults for every `swarm-routing` repository: the profile page,
default issue forms and PR template, the label taxonomy, the C++ style, and the
reusable workflows other repos call (`reusable-ns3-ci.yml`, `reusable-ns3-image.yml`,
`reusable-release.yml`, `reusable-benchmark-cell.yml`, `sync-labels.yml`).
Files here only take effect from `main` (GitHub reads community defaults and
`@main` workflow references from the default branch).

```
profile/README.md, ROADMAP.md, CONTRIBUTING.md   the org landing page, its phases, its invariants and conventions
ISSUE_TEMPLATE/, pull_request_template.md, labels.json   the default forms and the label taxonomy
SECURITY.md, CODE_OF_CONDUCT.md, SUPPORT.md, DCO, .github/FUNDING.yml   the org default community files
.clang-format, ruff.toml           the C++ style and the Python lint baseline
tools/<tool>/                       the org's scripts, each with --self-test (checks, org-sync, org-bot, epics, zenodo, docs-review, fidelity, protocol-review, pr-status, lit-search, repo-settings, release)
templates/                          what org-sync renders into each repository; templates/rulesets/: the settings profiles
.github/workflows/, .github/actions/   the reusable workflows other repos call, this repo's CI and bots, the bot token
docs/                               tools.md (every file, tool, workflow and self-test), where-to-look.md (the full task table)
```

Before adding, changing or running a tool or a workflow, read
[`docs/tools.md`](docs/tools.md): one line per file and directory, every
self-test and read-only run, and how a reusable workflow change is proven.

## Build & verify

No build. Before pushing:

```bash
pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1   # once, as ci.yml
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
python3 -I tools/checks/check-headers.py --self-test && python3 -I tools/checks/check-headers.py --dual '' .
# and the --self-test of every tool you changed: the exact commands are in docs/tools.md
pip install ruff==0.17.1 && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml
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
   `.h`/`.hpp`/`.cc`/`.cpp`/`.py`/`.sh` starts with
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
   swarm-core's; CI checks it, `check-headers.py --core-dep`), and a dual script imports no GPL-only code. Code coming from AntHocNet keeps its
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
   ns-3 adapter on `SwarmRoutingBase` (swarm-routing/ns3-swarm-core#14).
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
10. **Reusable workflows are a public contract.** Callers pin `@main`: never rename or remove an input, never change a default's meaning; add inputs with backward-compatible defaults. A breaking change needs a new file or a tag, announced in an issue in every caller repo.
11. **`labels.json` is the taxonomy.** Change it together with `CONTRIBUTING.md` and the issue forms; `sync-labels` never deletes labels, so a rename is a manual migration recorded in an issue.
12. **The issue forms stay AntHocNet's shape.** Same fields, same body sections; org-specific additions only (areas, Depends on, literature).

## Conventions

- Issues follow the org taxonomy ([CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#issues), from
  [AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)): one type label
  (`bug`/`enhancement`/`chore`/`documentation`/`verification`, plus `epic` for
  umbrellas), area label(s) (`protocol`/`adapter`/`ns3`/`benchmark`/
  `observability`/`packaging`/`learn-site`/`literature`), one `model:*`
  suggestion (a model on the Claude Pro plan), one `priority:P1|P2|P3` on
  non-epic issues (none on an epic), a
  `release:vX.Y.Z` label only when a release in the repository's ladder
  (`docs/roadmap.md`; until it lands, the org ROADMAP's release train)
  gates the issue: that label set is the version's scope,
  and the version is released when its issues are done (CONTRIBUTING
  "Cutting a release"). Labels come from `labels.json` via the `sync-labels`
  workflow, the shared `release:v0.1.0` to `release:v0.4.0` and
  `release:v1.0.0` among them; a version outside that set is added to
  `swarm-routing/.github`'s `labels.json` (and CONTRIBUTING's label table)
  when a ladder needs it, and reaches a repository when its `sync-labels` runs
  (monthly, or dispatched after the change merges),
  or, in a repository that keeps its own release labels (AntHocNet), created
  there with `gh label create release:vX.Y.Z` when its ladder adds the version.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Epics are listed where contributors look. In a public repository, this
  README's `## Epics` section and the org
  [ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics)
  are generated from the issues labelled `epic` by `swarm-routing/.github`'s
  `tools/epics/epics.py`. An open epic is Planned (no sub-issue closed) or In
  progress (some closed); it becomes Done or Dropped only when you close the
  epic itself (as completed or as not planned), even if every sub-issue is
  closed. Whenever you change an epic (open, close, rename or re-scope it, add
  or remove its `epic` label) or one of its sub-issues (close, reopen, add,
  unlink), refresh the lists in that PR or the next one. You need
  `swarm-routing/.github` checked out next to this repository and `gh` logged
  in (or `GH_TOKEN` set). Run `python3 ../.github/tools/epics/epics.py readme .`
  in the repository that owns the epic (for a sub-issue of another
  repository's epic, that repository, not this one), then
  `python3 tools/epics/epics.py roadmap ROADMAP.md` and
  `python3 tools/epics/epics.py profile profile/README.md` in `.github`. Never
  edit a generated section by hand; the weekly `epics` workflow in `.github`
  only reports drift. Private repositories are never listed
  and keep no generated section.
- Make minimal, reviewable changes; update the relevant doc/ADR when you change
  a documented decision.

## Git workflow

- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`, so it is a lowercase Conventional Commit
  (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR and
  the required checks, not an up-to-date branch. Bots push `bot/<name>` branches
  and open PRs; a release is the bump PR from `bot/release`, tagged after it
  merges (CONTRIBUTING "Cutting a release").
- A PR behind `main` may merge as it is: the ruleset does not require an
  up-to-date branch. Update it first
  (`gh api -X PUT "repos/<owner>/<repo>/pulls/<n>/update-branch"`, with
  `<owner>/<repo>` the PR's base repository and `<n>` its number) only when
  `main` changed what it touches (a template, a workflow, a required check),
  then merge after its CI on the updated branch. A
  repository with a merge queue (`merge_queue = true` in its `[settings]`)
  is not updated by hand: enable auto-merge and the queue tests each PR on
  the latest `main` and merges it (CONTRIBUTING "Merge when CI is green").
  Never force-push a branch someone else pushed. A behind `bot/release` PR is the exception:
  dispatch the release `bump` again, so the version and changelog are rebuilt
  on the new `main`.
- **Settings are code.** Repository settings, rulesets, required checks and the
  Actions allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in `swarm-routing/.github`,
  never in the UI or by a direct API write. A `templates/rulesets/` change
  applies on merge; a repo's `[settings]` change applies when `repo-settings`
  in `swarm-routing/.github` is dispatched with mode `apply` after the merge
  (the daily run only checks). A required check runs on every PR (no `paths:`
  filter; skip work inside a gate job instead) and is named exactly as its
  check run. A new third-party action goes into `defaults.json`
  `selected_actions` (`templates/rulesets/`) before or with the workflow that
  uses it: in the same PR in `swarm-routing/.github`, otherwise merged there
  first, or `repo-settings` refuses the repo.

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
  repository's #151 (swarm-routing/.github#277).
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
  check (`codecov/patch`, Sonar) is triaged, not waited on. A red `dco` on an
  outside contributor's commit still holds the PR until that author signs
  off; on the maintainer's or an agent's commits it is expected
  (swarm-routing/.github#212). `dco` is not a required check and runs on
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
- Releases are cut on request only: dispatch the release `bump` when the
  maintainer asks, once the version's `release:vX.Y.Z` issues are done and
  its exit criteria in the ladder (`docs/roadmap.md`, or the org ROADMAP's
  release train until it lands) are met; never approve a gated publish. A
  failed publish is recovered with "Re-run all jobs", never "Re-run failed
  jobs" (CONTRIBUTING "Cutting a release"). Never type a release's DOI: read
  it from Zenodo. After a public repository's release publishes, confirm the
  site saw it: a `[release-sync] <repo> <tag>` issue opens in
  `swarm-routing/swarm-routing.github.io` and a `release-sync.yml` run for
  that release ends green. If no issue appears within an hour, or no run for
  it is green, dispatch the site's `release-sync.yml` with `repository`
  (`owner/repo`) and `tag` and check that run (CONTRIBUTING "Cutting a
  release"); its weekly Monday run is only the backstop.
- Cite a paper in a public issue, PR or doc by its `https://doi.org/<DOI>`
  link, read from its record (`lit-search` confirms it), or, for a work with
  no DOI, by its publisher's or institution's page; never point into or name
  the private paper library there.

## Where to look

One line per task. Each row has a full entry in [`docs/where-to-look.md`](docs/where-to-look.md)
(the commands, the configuration, the issues behind it): read it before
changing what the row names.

| You want to… | Go to |
|--------------|-------|
| Change the CI every protocol repo runs | `.github/workflows/reusable-ns3-ci.yml` |
| Build a protocol's release or campaign image | `.github/workflows/reusable-ns3-image.yml` |
| Run one benchmark cell of any protocol repository | `.github/workflows/reusable-benchmark-cell.yml` |
| Cut a release of any org repository, or change how releases are made | `.github/workflows/reusable-release.yml` |
| Turn on SonarQube Cloud or Codecov for a C++ repo | `reusable-ns3-ci.yml` input `sonar`, `reusable-codecov.yml`, `templates/quality/` |
| Change the Python lint/coverage or the PR-title rule | `reusable-python-ci.yml` + `ruff.toml`; `reusable-pr-title.yml` |
| Change the licence rules or their gate | `tools/checks/check-headers.py`, `reusable-licence-check.yml`, CONTRIBUTING rule 1 |
| Change how outside contributions are accepted (DCO, contributor copyright lines) | CONTRIBUTING "Outside contributions", `tools/checks/check-dco.py`, `reusable-dco.yml` |
| Add or rename a label | `labels.json` + `CONTRIBUTING.md` + `ISSUE_TEMPLATE/` |
| List an org skill in every repo's AGENTS.md | `templates/agents/skills.md` |
| Change what every repo shares (org sections, badges, SECURITY, ADR template, Makefile) | `templates/` + `tools/org-sync/org_sync.py`; a template change turns every adopting repo's `org-sync` check red until its refresh PR lands |
| Bring a repo onto the templates | `tools/org-sync/org_sync.py init` (new repo) or `plan` → `apply` → `check` |
| Change the org security policy | `SECURITY.md`, `templates/SECURITY.md.in`; write no claim a repo cannot back |
| Change the C++ style | `.clang-format` |
| Change the org landing page | `profile/README.md` |
| Give a workflow the bot's token, or check the org App's permissions | `.github/actions/bot-token`; CONTRIBUTING "The bot's GitHub App" |
| Keep epic lists, org-managed files and protocol repositories' swarm-core pins current without hand PRs | `tools/org-bot/org_bot.py`, `org-bot.yml` |
| Check that every release is on Zenodo, or archive a missed one | `tools/zenodo/zenodo.py`, `zenodo.yml` |
| Register a repository for the OpenSSF Best Practices badge, or check its entry | `tools/bestpractices/bestpractices.py`, `bestpractices.yml` |
| Hold a repo's README, AI files and docs/ to the org standard | `tools/docs-review/check_docs.py`, `ai_files_review.py`, `ai-files-review.yml` |
| Check a diff against the org golden rules before review | `tools/protocol-review/check_invariants.py` |
| See open PRs' CI and review threads, wait for CI, or merge PRs that fall behind | `tools/pr-status/pr_status.py` |
| Confirm a reference, or find newer, citing, cited or related papers | `tools/lit-search/lit_search.py` |
| Change a repository's settings, rulesets, required checks, merge queue or Actions policy | its `.github/org-sync.toml` `[settings]`, `templates/rulesets/`, `tools/repo-settings/repo_settings.py` |
| Write or check a protocol's paper-fidelity sheet | `tools/fidelity/fidelity.py` |
| List, or refresh, the epics (README sections, ROADMAP, profile) | `tools/epics/epics.py`, `epics.yml` |
| Know where the org is going beyond ns-3, and which decisions wait on the maintainer | `ROADMAP.md` "Direction beyond ns-3"; epics #250, #251, #252, #272 |
| Make the agent files shorter, or the org's state readable by a new session | #277, #278, #281 under epic #141 |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`swarm-routing/AntHocNet`](https://github.com/swarm-routing/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
