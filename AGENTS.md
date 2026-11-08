# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/.github`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/danieljoppi/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

Org-wide defaults for every `swarm-routing` repository: the profile page,
default issue forms and PR template, the label taxonomy, the C++ style, and the
reusable workflows other repos call (`reusable-ns3-ci.yml`, `sync-labels.yml`).
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
tools/checks/check-headers.py   the licence-header gate (AntHocNet's rules, per-repo roots as flags)
tools/org-sync/org_sync.py      applies templates/ to a repo and checks drift (+ test_org_sync.py)
tools/epics/epics.py            the epic lists: each README's ## Epics, ROADMAP.md#epics, the profile's open epics (generated from issues)
templates/                      what org-sync renders: AGENTS.md/CLAUDE.md org sections, README badges,
                                SECURITY.md, LICENSE(-MIT), LICENSING.md, ADR template, Makefile per kind,
                                the org-sync workflow, the marketplace keys of .claude/settings.json,
                                the CodeRabbit settings (.coderabbit.yaml head/tail sections, #37)
SECURITY.md                     the org default security policy (repos without their own get it)
.github/FUNDING.yml             the org default Sponsor button (GitHub Sponsors: danieljoppi)
.github/workflows/         reusable-ns3-ci.yml, reusable-python-ci.yml, reusable-pr-title.yml, reusable-licence-check.yml,
                           reusable-org-sync-check.yml, sync-labels.yml, epics.yml, ci.yml
LICENSE, LICENSE-MIT, LICENSING.md   this repo is tooling: all of it MIT OR GPL-2.0-only except docs
```

## Build & verify

No build. Before pushing:

```bash
pip install actionlint-py shellcheck-py      # once
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
python3 -I tools/checks/check-headers.py --self-test && python3 -I tools/checks/check-headers.py --dual '' .
python3 -I tools/org-sync/test_org_sync.py   # org-sync against fixture repos
python3 -I tools/epics/epics.py --self-test     # the epic lists, on fixture data
pip install ruff==0.17.1 && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml
clang-format-18 --style=file:.clang-format --dump-config >/dev/null
```

A change to `reusable-ns3-ci.yml` is validated by running its step scripts in
an `ns3-dev` image against `swarm-routing/ns3-containers`' `test/fixtures/`
module (see that repo's AGENTS.md), then by a caller repo's PR.

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
   comments where needed), matching its directory in `LICENSING.md`. CI
   (`reusable-licence-check.yml`) checks it. A new directory gets its row in
   `LICENSING.md` in the same PR.
2. **The licence boundary only goes one way.** GPL code may use the dual
   parts; dual code never pulls GPL-only code in: a `core/` file includes only
   the C++ standard library and other `core/` files (CI checks it), and a dual
   script imports no GPL-only code. Code coming from AntHocNet keeps its
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
  `release:vX.Y.Z` label only when a roadmap gates the issue. Labels come from
  `labels.json` via the `sync-labels` workflow.
- Issue bodies: **Context** (evidence, numbers, links) · **Scope** ·
  **Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
  `swarm-routing/<repo>#N`) · **References**. Children of an epic say "Part of
  #N" and are linked as sub-issues. Comments you post end with the Claude Code
  footer.
- Issues migrated from AntHocNet carry `migrated` and start with *Migrated from
  `danieljoppi/AntHocNet#N`*.
- Epics are listed where contributors look: this README's `## Epics` section
  and the org [ROADMAP](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics)
  are generated from the issues labelled `epic` by `swarm-routing/.github`'s
  `tools/epics/epics.py`, which reads each status from the sub-issues
  (Planned, In progress, Done). When you open or close an epic, or close the
  first or last of its sub-issues, refresh them in that PR or the next one:
  `python3 ../.github/tools/epics/epics.py readme .` here, `roadmap
  ROADMAP.md` and `profile profile/README.md` in `.github`. Never edit a
  generated section by hand; a weekly check in `.github` reports drift.
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

## Where to look

| You want to… | Go to |
|--------------|-------|
| Change the CI every protocol repo runs | `.github/workflows/reusable-ns3-ci.yml` (quality inputs `strict-warnings`, `coverage`, `determinism`: CONTRIBUTING § Quality gates) |
| Change the Python lint/coverage or the PR-title rule | `reusable-python-ci.yml` + `ruff.toml`; `reusable-pr-title.yml` + CONTRIBUTING's type list |
| Change the licence rules or their gate | `tools/checks/check-headers.py` (+ its self-test), `reusable-licence-check.yml`, `CONTRIBUTING.md` rule 1, each repo's `LICENSING.md` |
| Add or rename a label | `labels.json` + `CONTRIBUTING.md` + `ISSUE_TEMPLATE/` |
| Change what every repo shares (AGENTS.md/CLAUDE.md org sections, badges, SECURITY, ADR template, Makefile targets) | `templates/` + `tools/org-sync/org_sync.py` (its docstring lists the item kinds; `ITEMS` in `items()`). A template change makes every adopting repo's `org-sync` check red until it runs `org_sync.py apply`: open those PRs with the change (the `org-repo` skill in `swarm-routing/skills` does it) |
| Bring a repo onto the templates | `python3 tools/org-sync/org_sync.py init <dir> --kind <kind>` (new repo) or write its `.github/org-sync.toml` and run `plan` → `apply` → `conflicts` → `check` (existing repo); CI: `reusable-org-sync-check.yml` |
| Change the org security policy | `SECURITY.md` (served to every repo without its own) and `templates/SECURITY.md.in` (a repo's own); write no claim a repo cannot back |
| Change the C++ style | `.clang-format` (repos without their own use it in CI) |
| Change the org landing page | `profile/README.md` |
| List, or refresh, the epics (README sections, ROADMAP, profile) | `tools/epics/epics.py` (`readme`, `roadmap`, `profile`, `check-all`; `--self-test`), the weekly `epics.yml`; CONTRIBUTING "Epics are the public plan" |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`danieljoppi/AntHocNet`](https://github.com/danieljoppi/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
