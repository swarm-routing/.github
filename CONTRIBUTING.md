# Contributing to swarm-routing

Org-wide defaults. A repository's own `CONTRIBUTING.md` overrides this file.
These conventions come from [`danieljoppi/AntHocNet`](https://github.com/danieljoppi/AntHocNet),
the source repository the org was split out of; its
[ADR-0013](https://github.com/danieljoppi/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md)
is the long form.

## Invariants (every repo)

1. **SPDX header.** Every original `.h`, `.cc`, `.py` starts with
   ```cpp
   // Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
   // SPDX-License-Identifier: MIT
   ```
   (`#` comments in Python.) Never copy GPLv2 code from ns-3's `src/aodv`,
   `src/olsr` & co.; implement against public ns-3 interfaces. CI checks the header.
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
   transient artifacts `retention-days` ≤ 7.
6. **Comparator arms** (protocols we did not design) clear three gates before
   their numbers count: a fidelity sheet from the paper, the per-PR delivery
   smoke, and an anchor reproducing the paper's own trend.

## Issues

Every finding, bug and decision is an issue, never a chat message or a file.

**Body shape:** **Context** (evidence, numbers, links) · **Scope** ·
**Acceptance criteria** (checkboxes) · **Depends on** (cross-repo form
`swarm-routing/<repo>#N`) · **References**. Children of an epic say
"Part of #N" and are linked as sub-issues.

**Labels** ([`labels.json`](labels.json), applied by
[`sync-labels.yml`](.github/workflows/sync-labels.yml)):

| Kind | Rule | Labels |
|---|---|---|
| Type | exactly one; umbrellas add `epic` | `bug`, `enhancement`, `chore`, `documentation`, `verification` (+ `question`, `handoff`) |
| Area | one or more | `protocol`, `adapter`, `ns3`, `benchmark`, `observability`, `packaging`, `learn-site`, `literature` |
| Model | exactly one: what a wrong first pass costs, not code volume | `model:haiku-4.5` (mechanical), `model:sonnet-5` (plumbing, tooling, docs), `model:opus-4.8` (protocol semantics, root cause, CI-validated adapter work), `model:fable-5` (architecture, greenfield) |
| Priority | exactly one on non-epic issues | `priority:P1` (regression / invalidates numbers), `priority:P2` (gates a result or feature), `priority:P3` (valuable, not blocking) |
| Release | only when a roadmap gates the issue | `release:vX.Y.Z` |

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
  Commit (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Merge when CI is green.

## AI agents

Every repo carries a `CLAUDE.md` (imports `AGENTS.md`; working defaults,
response style, handoffs as issues) and an `AGENTS.md` (what the repo is,
build & verify, golden rules, conventions, where to look), in the shape of
AntHocNet's. Change a convention here and in each repo's `AGENTS.md` together.
