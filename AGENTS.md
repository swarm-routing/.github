# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/.github`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/danieljoppi/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

Org-wide defaults for every `swarm-routing` repository: the profile page,
default issue forms and PR template, the label taxonomy, the C++ style, and the
reusable workflows other repos call (`reusable-ns3-ci.yml`, `reusable-ns3-image.yml`,
`reusable-release.yml`, `reusable-benchmark-cell.yml`, `sync-labels.yml`).
Files here only take effect from `main` (GitHub reads community defaults and
`@main` workflow references from the default branch).

```
profile/README.md          org landing page
ROADMAP.md                 the org's phases, exit criteria and non-goals (epics carry the work)
CONTRIBUTING.md            org invariants + issue/label conventions (default for every repo)
ISSUE_TEMPLATE/            default issue forms (AntHocNet's set + literature)
pull_request_template.md   default PR template
labels.json                the label taxonomy (source of truth)
.clang-format              LLVM-based C++20 style
ruff.toml                  the Python lint baseline (explicit rules), used where a repo has none
tools/checks/check-headers.py   the licence-header gate (AntHocNet's rules, per-repo roots as flags; contributor copyright lines beneath the org line)
tools/checks/check-dco.py       the DCO gate of reusable-dco.yml: every PR commit's Signed-off-by matches its author email (members, the org App and Dependabot exempt)
tools/checks/check-swarm-core-pin.py   a protocol's swarm-core pin: one commit everywhere, and swarm-core main's core/ (reusable-swarm-core-pin.yml)
DCO                             the Developer Certificate of Origin 1.1, verbatim (CONTRIBUTING "Outside contributions")
tools/org-sync/org_sync.py      applies templates/ to a repo and checks drift (`check --changed-only BASE`: only a PR's own drift fails, the base's warns); `seeds` / `reseed FILE` for the repo-owned seeds (+ test_org_sync.py)
tools/epics/epics.py            the epic lists: each README's ## Epics, ROADMAP.md#epics, the profile's open epics (generated from issues)
tools/org-bot/org_bot.py        opens the refresh PRs across the org: epic lists (epics.py) and templates (org_sync.py apply)
tools/zenodo/zenodo.py          every release on Zenodo: checks each repo's releases against its concept record, archives the missed ones
tools/docs-review/check_docs.py   a repo's README, AI files and docs/ against the org standard (AntHocNet's): badges, explanation, site page, ns-3 image, layout, sections, links; the AI files' facts (paths, planned paths, open issues with --online, org-rule contradictions, required checks)
tools/docs-review/ai_files_review.py   the weekly AI-files review: check_docs.py's AI-files pass on every public repo, one `[docs] AI files: N finding(s)` issue per repo, opened, updated in place, closed when clean
tools/fidelity/fidelity.py      a protocol's docs/fidelity.md: the org shape (skeleton), valid sources and the list of unknowns (check), each locator and table value against the paper's text (verify), the review row (row)
tools/protocol-review/check_invariants.py   the mechanical org golden rules (1-5, 8, 9) on a repo's diff, a line per rule the diff touches, exit 1 on a FAIL; rules 6 and 7 stay the reviewer's, with HINT lines at the likely spots
tools/pr-status/pr_status.py    open PRs across repos: `list`, `threads` and `wait` (read-only) print a line per PR (head, CI verdict and counts, required checks missing on the head, workflows that ended in `startup_failure`, mergeable state) and per unresolved review thread (severity · title · path:line · id); a missing required check is never a pass; `merge` writes: it updates a behind PR, waits for green and squash-merges, one PR at a time per repo
tools/release/fixture/         the release self-test's caller: the minimal Commitizen config (.cz.toml) and a `make dist`
tools/lit-search/lit_search.py  references and new papers from free sources only: confirm a DOI (Crossref vs Semantic Scholar and OpenAlex) or a title, the works citing or cited by a paper (OpenCitations + Semantic Scholar), search, related
tools/repo-settings/repo_settings.py   each repo's description, homepage, topics, merge settings and features, `main` and `release-tags` rulesets, security features, Actions policy (incl. fork-PR approval) and `release` environment as code: `plan`/`check` (read-only diff), `apply` (only the differences)
templates/rulesets/             the ruleset profiles repo_settings.py applies (protocol, tooling, data, site, merge-only): merge settings + the ruleset in the API shape; defaults.json: the parts every profile shares (features, security, Actions policy and its allowed actions, the tag ruleset, the release environment)
templates/                      what org-sync renders: AGENTS.md/CLAUDE.md org sections (incl. Agent skills), README badges,
                                SECURITY.md, LICENSE(-MIT), LICENSING.md, ADR template, Makefile per kind,
                                the org-sync, dco and Scorecard workflows, the marketplace keys of .claude/settings.json,
                                the CodeRabbit settings (.coderabbit.yaml head/tail sections, #37),
                                codeowners/: .github/CODEOWNERS, a seed with the org's invariant paths per kind as its last section (#31),
                                quality/: the .codecov.yml and sonar-project.properties seeds of C++ repos
SECURITY.md                     the org default security policy (repos without their own get it)
CODE_OF_CONDUCT.md              the org default code of conduct: Contributor Covenant 2.1, reports to the maintainer's GitHub profile (no email)
SUPPORT.md                      the org default support policy: issues for bugs, features and questions, no private support
.github/FUNDING.yml             the org default Sponsor button (GitHub Sponsors: danieljoppi)
.github/actions/bot-token/      the bots' token: the org GitHub App's installation token, else ORG_BOT_TOKEN (#21; CONTRIBUTING "The bot's GitHub App")
.github/workflows/         reusable-ns3-ci.yml, reusable-ns3-image.yml, reusable-release.yml, reusable-benchmark-cell.yml, reusable-python-ci.yml,
                           reusable-pr-title.yml, reusable-licence-check.yml, reusable-dco.yml, reusable-org-sync-check.yml, reusable-codecov.yml, reusable-scorecard.yml, reusable-swarm-core-pin.yml,
                           sync-labels.yml, epics.yml, ai-files-review.yml, zenodo.yml, org-bot.yml, repo-settings.yml, scorecard.yml, ci.yml, ns3-image-selftest.yml, release-selftest.yml,
                           benchmark-cell-selftest.yml
LICENSE, LICENSE-MIT, LICENSING.md   this repo is tooling: all of it MIT OR GPL-2.0-only except docs
```

## Build & verify

No build. Before pushing:

```bash
pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1   # once, as ci.yml
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
python3 -I tools/checks/check-headers.py --self-test && python3 -I tools/checks/check-headers.py --dual '' .
python3 -I tools/checks/check-dco.py --self-test   # the DCO gate: signed, unsigned, mismatched, exempt (member, write access, bots, merges), a real git history
python3 -I tools/checks/check-swarm-core-pin.py --self-test   # against a local swarm-core and fixture repos
python3 -I tools/org-sync/test_org_sync.py   # org-sync against fixture repos
python3 -I tools/epics/epics.py --self-test     # the epic lists, on fixture data
python3 -I tools/zenodo/zenodo.py --self-test   # the Zenodo check and archive, against a fake Zenodo
python3 -I tools/org-bot/org_bot.py --self-test # the refresh PRs, against local bare repos and a fake GitHub
python3 -I tools/docs-review/check_docs.py --self-test   # the docs standard and the AI-files facts, a passing and a failing fixture repo per check
python3 -I tools/docs-review/check_docs.py ../AntHocNet --online   # read-only, a real repo's docs and AI files (issue states through gh)
python3 -I tools/docs-review/ai_files_review.py --self-test   # the weekly review's issue sync, against local bare repos and a fake GitHub
python3 -I tools/docs-review/ai_files_review.py run --dry-run --repos .github,skills   # read-only, what the weekly run would open, update or close
python3 -I tools/fidelity/fidelity.py --self-test   # the fidelity-sheet checker, on fixture sheets
python3 -I tools/protocol-review/check_invariants.py --self-test   # a passing and a failing fixture repo per checked rule; a hinted and an unhinted one for 6 and 7
python3 -I tools/pr-status/pr_status.py --self-test   # the PR view, against a fake GitHub (CI states, a startup_failure run and missing required checks, threads, a CodeRabbit body reduced to its heading, wait), and merge against a simulated one (behind -> update -> merged, sequence, failing check, open thread, conflict, draft, refused, unreported required check, startup failure, already merged)
python3 -I tools/lit-search/lit_search.py --self-test   # confirm, citing, refs, search, related on recorded responses of each source, a source down or rate-limited, keys never leaked
python3 -I tools/repo-settings/repo_settings.py --self-test   # plan, check, apply against a fake GitHub (each field's drift, ruleset create/update, unmanaged ruleset left alone, private masked, 403 refused, dry run; merge_queue rule, its table overrides and validation, refused without a merge_group trigger behind each required check; security on in order, own CodeQL kept, private unsupported, Actions policy and an uncovered action refused, fork-PR approval for all outside contributors (a note on a private repository), 409 org policy, release environment, idempotent)
python3 -I tools/org-bot/org_bot.py run --dry-run --repos .github,Termite   # read-only, what it would propose
python3 -I tools/zenodo/zenodo.py sync --repo swarm-routing/AntHocNet --dry-run   # read-only, the real records
python3 -I tools/pr-status/pr_status.py list --repos .github,skills   # read-only, the open PRs and their unresolved threads
python3 -I tools/pr-status/pr_status.py merge --dry-run .github#N   # read-only, what merge would do now (would update / would merge / would wait)
python3 -I tools/lit-search/lit_search.py confirm 10.1613/jair.530   # read-only, free: Crossref, Semantic Scholar, OpenAlex agree
python3 -I tools/repo-settings/repo_settings.py plan .github skills   # read-only, live settings vs each repo's [settings]
pip install ruff==0.17.1 && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml
clang-format-18 --style=file:.clang-format --dump-config >/dev/null
```

A change to `reusable-ns3-ci.yml` is validated by running its step scripts in
an `ns3-dev` image against `swarm-routing/ns3-containers`' `test/fixtures/`
module (see that repo's AGENTS.md), then by a caller repo's PR. A change to
`reusable-benchmark-cell.yml` runs `benchmark-cell-selftest.yml` on its PR (one
build-mode cell); its prebuilt mode is proven by a protocol repo's caller. A change to
`reusable-ns3-image.yml` runs `ns3-image-selftest.yml` on its PR (build and
test only); its push, sign and attest steps are proven by a `push: true`
caller after merge. A change to `reusable-release.yml` runs `release-selftest.yml`
on its PR: a dry run on `tools/release/fixture/` (bump to v0.1.0, `make dist`,
checksums, SBOM, real attestations and their verification, nothing pushed),
then a check of every file it would have published; its bump PR (`propose`)
and its tag-and-publish job are proven by the first caller's release
(ns3-tools#26).

## Golden rules (invariants — do not break)

Org-wide (1–9), then this repo's own.

1. **Licensing per directory, as AntHocNet** ([`LICENSING.md`](LICENSING.md);
   AntHocNet [LICENSING.md](https://github.com/danieljoppi/AntHocNet/blob/main/LICENSING.md),
   [ADR-0028](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0028-core-is-dual-licensed.md)). A
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
   shared module is `swarm-core` (`#include "ns3/swarm-core-module.h"`).
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
  [AntHocNet ADR-0013](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)): one type label
  (`bug`/`enhancement`/`chore`/`documentation`/`verification`, plus `epic` for
  umbrellas), area label(s) (`protocol`/`adapter`/`ns3`/`benchmark`/
  `observability`/`packaging`/`learn-site`/`literature`), one `model:*`
  recommendation, one `priority:P1|P2|P3` on non-epic issues, a
  `release:vX.Y.Z` label only when a release in the repository's ladder
  (`docs/roadmap.md`; until it lands, the org ROADMAP's release train)
  gates the issue: that label set is the version's scope,
  and the version is released when its issues are done (CONTRIBUTING
  "Cutting a release"). Labels come from `labels.json` via the `sync-labels`
  workflow.
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
  only reports drift. Private repositories (such as `papers`) are never listed
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
- **`main` takes no direct push**, in any repo: its ruleset requires a PR, an
  up-to-date branch and the required checks. Bots push `bot/<name>` branches
  and open PRs; a release is the bump PR from `bot/release`, tagged after it
  merges (CONTRIBUTING "Cutting a release").
- When a PR falls behind `main`, update it
  (`gh api -X PUT "repos/<owner>/<repo>/pulls/<n>/update-branch"`, with
  `<owner>/<repo>` the PR's base repository and `<n>` its number) and merge PRs one at a time, each after its CI on the updated branch. A
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

## Where to look

| You want to… | Go to |
|--------------|-------|
| Change the CI every protocol repo runs | `.github/workflows/reusable-ns3-ci.yml` (quality inputs `strict-warnings`, `coverage`, `determinism`: CONTRIBUTING § Quality gates) |
| Build a protocol's release or campaign image | `.github/workflows/reusable-ns3-image.yml` (`FROM` a resolved ns3-dev digest, `ns3-build-contrib`, `test.py`, then push, cosign, provenance, SBOM; caller examples and verify commands in its header), self-tested by `ns3-image-selftest.yml` (`push: false`, ns3-containers' `swarm-hello`); CONTRIBUTING § Images |
| Run one benchmark cell of any protocol repository (a change test, or a cell of a released run) | `.github/workflows/reusable-benchmark-cell.yml` (an image by digest, `source_sha` checked out and verified whatever the dispatch ref, prebuilt mode `--no-build` or build mode with pinned dependencies, the `##PROV##` line; caller and its safe pattern, #160, in its header), dispatched by `ns3-campaign` (`swarm-routing/ns3-tools`), self-tested by `benchmark-cell-selftest.yml`; CONTRIBUTING § Benchmark cells, epic #156 |
| Cut a release of any org repository (or change how releases are made) | `.github/workflows/reusable-release.yml` (Commitizen bump from Conventional Commits, first release v0.1.0, the caller's `make dist`, `SHA256SUMS`, CycloneDX SBOM, SLSA provenance as `*.intoto.jsonl`, the verify commands in the notes; mode `bump` opens the `chore(release): bump version A to B` PR from `bot/release` with the org App's token, its merge releases: tag on the merged commit, GitHub release; mode `dry-run`; caller example, permissions and verify commands in its header), self-tested by `release-selftest.yml` (dry run on `tools/release/fixture/`); CONTRIBUTING § Releases and DOIs, ROADMAP § Releases |
| Turn on SonarQube Cloud or Codecov for a C++ repo | `reusable-ns3-ci.yml` input `sonar` (+ `SONAR_TOKEN`; `sonar-python-coverage` to import the Python job's coverage into the same analysis), a job calling `reusable-codecov.yml`; seeds `templates/quality/`; badges `sonar`/`codecov` in its `org-sync.toml`; CONTRIBUTING § Quality gates |
| Change the Python lint/coverage or the PR-title rule | `reusable-python-ci.yml` + `ruff.toml`; `reusable-pr-title.yml` + CONTRIBUTING's type list |
| Change the licence rules or their gate | `tools/checks/check-headers.py` (+ its self-test), `reusable-licence-check.yml`, `CONTRIBUTING.md` rule 1, each repo's `LICENSING.md` |
| Change how outside contributions are accepted (DCO sign-off, inbound = outbound, contributor copyright lines) | `CONTRIBUTING.md` "Outside contributions", `DCO`, `tools/checks/check-dco.py` (+ its self-test), `reusable-dco.yml`, its caller `templates/workflows/dco.yml` (org-sync places it in every repo; not a required check yet, #179) |
| Add or rename a label | `labels.json` + `CONTRIBUTING.md` + `ISSUE_TEMPLATE/` |
| List an org skill in every repo's AGENTS.md (when it ships in the `swarm-routing` plugin) | `templates/agents/skills.md` (task, script, skill); a skill one repo uses stays in that repo's `.claude/skills/` |
| Change what every repo shares (AGENTS.md/CLAUDE.md org sections, badges, SECURITY, ADR template, Makefile targets) | `templates/` + `tools/org-sync/org_sync.py` (its docstring lists the item kinds; `ITEMS` in `items()`). A template change makes every adopting repo's `org-sync` check red on its next push to `main` until it runs `org_sync.py apply` (on a PR or a merge group only the drift the change brings in fails, an item that did not drift at the base or that it edits by hand; drift already on the base is a warning, `check --changed-only BASE`, #159): open those PRs with the change (the `org-repo` skill of the `swarm-routing` plugin in `swarm-routing/skills` does it; org-bot opens them on its own after the push). Seeds (SECURITY.md, Makefile, LICENSING.md, …) are the repo's once written, so a template or config change never reaches them: `org_sync.py seeds [REPO]` says which differ from today's render (information, exit 0; org-bot lists them in its PR body), `org_sync.py reseed FILE [REPO]` shows the diff and writes the fresh render of that one seed |
| Bring a repo onto the templates | `python3 tools/org-sync/org_sync.py init <dir> --kind <kind>` (new repo) or write its `.github/org-sync.toml` and run `plan` → `apply` → `conflicts` → `check` (existing repo); CI: `reusable-org-sync-check.yml` |
| Change the org security policy | `SECURITY.md` (served to every repo without its own) and `templates/SECURITY.md.in` (a repo's own); write no claim a repo cannot back |
| Change the C++ style | `.clang-format` (repos without their own use it in CI) |
| Change the org landing page | `profile/README.md` |
| Give a workflow the bot's token, or check the org GitHub App's permissions and repository scope | `.github/actions/bot-token` (App token from `BOT_APP_ID` + `BOT_APP_PRIVATE_KEY`, else `ORG_BOT_TOKEN`; used by `org-bot.yml`, `repo-settings.yml`, `repo-metadata.yml`). The App: org-owned, no webhook, installed on **all repositories**; repository permissions Administration, Contents, Pull requests, Issues, Workflows, Actions, Dependabot alerts, Secret scanning alerts, Environments: read and write, Metadata: read (#21); CONTRIBUTING "The bot's GitHub App" |
| Keep every repo's epic list and org-managed files current without hand PRs | `tools/org-bot/org_bot.py` (`run --task` `epics`, `org-sync` or `all`; `--self-test`), `org-bot.yml` (daily, on template pushes; the org GitHub App's token, else secret `ORG_BOT_TOKEN`); CONTRIBUTING "Automation" |
| Check that every release is on Zenodo, or archive a missed one | `tools/zenodo/zenodo.py` (`repos`, `status`, `sync`; `--self-test`), the daily `zenodo.yml` (secret `ZENODO_TOKEN`); CONTRIBUTING "Releases and DOIs" |
| Hold a repo's README, AGENTS/CLAUDE/CONTEXT and docs/ to the org standard, and keep the AI files' facts true | `tools/docs-review/check_docs.py [REPO] [--online]` (`[docs]` table in its `.github/org-sync.toml`: `arena_id`, `uses_image`; `--self-test`). The AI-files pass (#142) warns on missing or still-planned paths, closed issues written as open (`--online`), text an org rule replaced (its `CONTRADICTIONS` table, each with its source) and unknown required checks, outside the org-sync sections. Weekly across the org: `ai-files-review.yml` runs `tools/docs-review/ai_files_review.py` (`run [--repos A,B] [--dry-run] [--offline]`; `--self-test`), one `[docs] AI files` issue per public repo (#143); the `docs-review` skill in `swarm-routing/skills` |
| Check a diff against the org golden rules before review | `tools/protocol-review/check_invariants.py [REPO] --base origin/main [--pr-body FILE] [--json]` (per-repo `[review]` table in its `.github/org-sync.toml`; `--self-test`); the `protocol-review` skill in `swarm-routing/skills` |
| See every open PR's CI, mergeable state and unresolved review threads, wait for CI, or merge PRs that keep falling behind | `tools/pr-status/pr_status.py` (`list [--repos A,B] [--author L]`, `threads REPO#N [--all]`, `wait REPO#N…`, `merge REPO#N… [--dry-run] [--timeout S]`; `--json` on each; `--self-test`); the `pr-shepherd` skill in `swarm-routing/skills` |
| Confirm a reference, or find newer, citing, cited or related papers | `tools/lit-search/lit_search.py` (`confirm DOI` / `confirm --title`, `citing`, `refs`, `search [--crossref] [--preprints]`, `related`; `--library FILE…` marks known DOIs; `--self-test`): free sources only (Crossref, Semantic Scholar, OpenCitations, arXiv, OpenAlex single records), OpenAlex search only with a free `OPENALEX_API_KEY`; the `lit-search` skill in `swarm-routing/skills` |
| Change a repository's description, homepage, topics, merge settings, features, rulesets, required checks, merge queue (`merge_queue = true`, after its required-check workflows run `on: merge_group`), security features, Actions policy or release environment | its `.github/org-sync.toml` `[settings]` table (a settings-only file, without `kind`, where org-sync manages nothing), the profiles in `templates/rulesets/` and their shared `defaults.json` (a new third-party action goes into its `selected_actions.patterns_allowed` in the same PR as the workflow that uses it); `tools/repo-settings/repo_settings.py` (`plan`, `check`, `apply [--dry-run]`; `--self-test`), applied by `repo-settings.yml` on push and checked daily (the org GitHub App's token, else secret `ORG_BOT_TOKEN`: CONTRIBUTING "Automation" lists the permissions either needs) |
| Write or check a protocol's paper-fidelity sheet | `tools/fidelity/fidelity.py` (`skeleton`, `check`, `verify --text KEY=<pdfx text>`, `row`; `--self-test`); the `fidelity-sheet` skill in `swarm-routing/skills` (plugin `swarm-routing`) |
| List, or refresh, the epics (README sections, ROADMAP, profile) | `tools/epics/epics.py` (`readme`, `roadmap`, `profile`, `check-all`; `--self-test`), the weekly `epics.yml`; CONTRIBUTING "Epics are the public plan" |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`danieljoppi/AntHocNet`](https://github.com/danieljoppi/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
