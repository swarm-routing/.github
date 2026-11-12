# swarm-routing

Swarm-intelligence and adaptive routing protocols for MANETs and LEO
constellations, implemented cleanly on **ns-3** and benchmarked against each
other on identical seeds.

The org grew out of [**AntHocNet**](https://github.com/swarm-routing/AntHocNet)
(Di Caro, Ducatelle & Gambardella, 2005), the source repository, which now
lives here too: its shared infrastructure, comparator arms and benchmark
tooling are moving into their own repositories so each protocol can be its
own citable repository.

## Why this exists

I am [Daniel Joppi](https://github.com/danieljoppi) ([LinkedIn](https://www.linkedin.com/in/danieljoppi)). I have more than 20
years of experience building high-scale software, delivery pipelines and the
architecture of new systems. AntHocNet started as my college project: I began
implementing the protocol in 2008 on NS-2 and put the code on GitHub in
[January 2016](https://github.com/swarm-routing/AntHocNet/commit/b7ac7d0f24).

I came back to it to put AI to a real test. Working with Claude Opus, I
restructured the code so the algorithm no longer depends on one NS-2 version
(a simulator-free `core/` behind thin adapters), moved it to ns-3, and grew it
into an organisation that implements and compares other swarm protocols on the
same footing. My main motivation is to find out how far a project can be
structured and organised using only AI, with tests, determinism checks and
paired benchmarks as the safeguard that the implementation stays correct.

That is why the work lives in tickets and roadmaps rather than in anyone's
head: every issue carries its context, acceptance criteria and links, so any
person, with any AI assistant, can take a ticket as their starting context and
begin an implementation or a new investigation.

The last two columns are live: each repository's SonarQube Cloud quality gate
and its Codecov line coverage (report-only, uploaded by CI from the repository's
own code). A dash means not measured yet: no code, or no analysis set up.

| Repository | What it is | Quality gate | Coverage |
|---|---|---|---|
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | `ghcr.io/swarm-routing/ns3-dev` images: ns-3 pre-built (debug / sanitized / optimized), contrib modules compile in seconds | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_ns3-containers&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_ns3-containers) | — |
| [ns3-swarm-core](https://github.com/swarm-routing/ns3-swarm-core) | The `swarm-core` contrib module: shared primitives (visited path, LE codecs, pheromone table, route decision) and ns-3 cross-layer glue | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_ns3-swarm-core&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_ns3-swarm-core) | [![codecov](https://codecov.io/gh/swarm-routing/ns3-swarm-core/graph/badge.svg)](https://codecov.io/gh/swarm-routing/ns3-swarm-core) |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | Diagnostic probes, comparison arenas, the `ns3-tool` CLI (sweep, compare, diagnose, scaffold) | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_ns3-tools&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_ns3-tools) | [![codecov](https://codecov.io/gh/swarm-routing/ns3-tools/graph/badge.svg)](https://codecov.io/gh/swarm-routing/ns3-tools) |
| [ARA](https://github.com/swarm-routing/ARA) | Ant-Colony-Based Routing Algorithm (Güneş et al., 2002) | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_ARA&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_ARA) | — |
| [BeeAdHoc](https://github.com/swarm-routing/BeeAdHoc) | Honeybee routing (Wedde & Farooq, 2005) | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_BeeAdHoc&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_BeeAdHoc) | — |
| [Termite](https://github.com/swarm-routing/Termite) | Stigmergic routing in data packets, no control ants (Roth & Wicker, 2003/2005). `core/` and ns-3 module in progress (Phase 5) | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_Termite&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_Termite) | — |
| [HOPNET](https://github.com/swarm-routing/HOPNET) | Ant routing over zones (Wang, 2007). `core/` in progress; ns-3 module next | — | — |
| [benchmarks](https://github.com/swarm-routing/benchmarks) | Immutable 20-seed datasets, paired verdicts, reproducibility manifests | — | — |
| [swarm-routing.github.io](https://swarm-routing.github.io) | Colony Arena: interactive docs, visualizers, leaderboard | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_swarm-routing.github.io&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_swarm-routing.github.io) | — |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | The reference AntHocNet implementation, the colony the org grew out of | [![Quality Gate](https://sonarcloud.io/api/project_badges/measure?project=swarm-routing_AntHocNet&metric=alert_status)](https://sonarcloud.io/summary/new_code?id=swarm-routing_AntHocNet) | [![codecov](https://codecov.io/gh/swarm-routing/AntHocNet/graph/badge.svg)](https://codecov.io/gh/swarm-routing/AntHocNet) |

## Open epics: pick something up

The org is set up for people and AI agents to work side by side: every
repository has an `AGENTS.md` (its rules, how to build and verify) and every
open sub-issue of an epic carries a `priority:*` and a `model:*` label.
Choose an epic, take one of its open sub-issues, and follow the repository's
`AGENTS.md`. What is already done, per repository:
[ROADMAP.md, Epics](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#epics).

Starting a fresh session, or handing work to an AI chat? Every workstream has
a [`handoff` issue](https://github.com/search?q=org%3Aswarm-routing+label%3Ahandoff+state%3Aopen&type=issues)
written for a reader with no history: the goal, the state, the next steps in
order, the commands and the pitfalls. The ROADMAP's
[Where to start](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md#where-to-start)
lists them in the order that matters.

<!-- epics:begin -->
<!-- Generated by swarm-routing/.github tools/epics/epics.py from the issues labelled `epic`; edit the issues, then re-run it. -->

| Repository | Epic | Status | Sub-issues closed |
|------------|------|--------|-------------------|
| [.github](https://github.com/swarm-routing/.github) | [#6](https://github.com/swarm-routing/.github/issues/6) org repo template — security policy, README badges and community files, applied and kept in sync by a tool and a skill | In progress | 15 / 28 |
| [.github](https://github.com/swarm-routing/.github) | [#14](https://github.com/swarm-routing/.github/issues/14) Repository hardening for every org repo: Scorecard, rulesets, merge policy, CI hygiene | In progress | 5 / 18 |
| [.github](https://github.com/swarm-routing/.github) | [#50](https://github.com/swarm-routing/.github/issues/50) One repository per swarm protocol: create the missing ones (Termite, HOPNET) | In progress | 2 / 3 |
| [.github](https://github.com/swarm-routing/.github) | [#107](https://github.com/swarm-routing/.github/issues/107) ns-3 images: every protocol release and campaign builds on ns3-containers | In progress | 6 / 7 |
| [.github](https://github.com/swarm-routing/.github) | [#141](https://github.com/swarm-routing/.github/issues/141) AI files stay correct: automated review of AGENTS.md and CLAUDE.md in every repo | In progress | 1 / 11 |
| [.github](https://github.com/swarm-routing/.github) | [#150](https://github.com/swarm-routing/.github/issues/150) CI time: every job under its budget | In progress | 1 / 4 |
| [.github](https://github.com/swarm-routing/.github) | [#156](https://github.com/swarm-routing/.github/issues/156) benchmarks: each protocol repo benchmarks its changes, swarm-routing/benchmarks records every release | In progress | 2 / 14 |
| [.github](https://github.com/swarm-routing/.github) | [#251](https://github.com/swarm-routing/.github/issues/251) Roadmap by tracks (protocols on ns-3, portable runtime, research, infrastructure) and the ticket clean-up that goes with it | In progress | 1 / 8 |
| [.github](https://github.com/swarm-routing/.github) | [#307](https://github.com/swarm-routing/.github/issues/307) docs/references.bib in every repository, DOI links first, sections generated and checked | In progress | 2 / 13 |
| [.github](https://github.com/swarm-routing/.github) | [#35](https://github.com/swarm-routing/.github/issues/35) code quality across the org — order of work and maintainer decisions | Planned | no sub-issues yet |
| [.github](https://github.com/swarm-routing/.github) | [#48](https://github.com/swarm-routing/.github/issues/48) Other simulators: container and tooling repos for OMNeT++/INET, Veins and CORE/EMANE (deferred; ns-3 first) | Planned | no sub-issues yet |
| [.github](https://github.com/swarm-routing/.github) | [#216](https://github.com/swarm-routing/.github/issues/216) every public repository releases and is archived on zenodo: ns3-containers, benchmarks, skills, the site and .github too | Planned | 0 / 5 |
| [.github](https://github.com/swarm-routing/.github) | [#250](https://github.com/swarm-routing/.github/issues/250) Portable runtime: one host contract, a discrete-event host and a Linux daemon, then real computers, tested on the same scenes at every step | Planned | 0 / 10 |
| [.github](https://github.com/swarm-routing/.github) | [#252](https://github.com/swarm-routing/.github/issues/252) A swarm protocol of our own, designed from what the five implementations measured | Planned | 0 / 4 |
| [.github](https://github.com/swarm-routing/.github) | [#272](https://github.com/swarm-routing/.github/issues/272) Routing security: one threat model, shared adversaries, default-off defences per protocol, secure comparators | Planned | 0 / 4 |
| [.github](https://github.com/swarm-routing/.github) | [#322](https://github.com/swarm-routing/.github/issues/322) Standalone discrete-event host: every core run without ns-3, deterministic, on the same scenes | Planned | 0 / 3 |
| [.github](https://github.com/swarm-routing/.github) | [#323](https://github.com/swarm-routing/.github/issues/323) Linux daemon host: every core over real sockets, packaged for amd64 and arm64 | Planned | 0 / 4 |
| [.github](https://github.com/swarm-routing/.github) | [#324](https://github.com/swarm-routing/.github/issues/324) Emulation: the daemons on CORE/EMANE, real stacks over emulated radio links | Planned | no sub-issues yet |
| [.github](https://github.com/swarm-routing/.github) | [#325](https://github.com/swarm-routing/.github/issues/325) Raspberry Pi testbed: the protocols on real boards, run and judged by one command | Planned | 0 / 1 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#64](https://github.com/swarm-routing/AntHocNet/issues/64) Abstract discrete-event testbench in core/tests — trend regression without a simulator | In progress | 1 / 2 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#109](https://github.com/swarm-routing/AntHocNet/issues/109) Publish the AntHocNet implementation (reproducibility + cross-simulator paper) | In progress | 1 / 4 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#328](https://github.com/swarm-routing/AntHocNet/issues/328) 5-star open-source packaging — visibility, supply-chain trust, onboarding, docs site | In progress | 15 / 25 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#32](https://github.com/swarm-routing/AntHocNet/issues/32) Add an OMNeT++/INET adapter (third simulator target) | Planned | 0 / 4 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#65](https://github.com/swarm-routing/AntHocNet/issues/65) CORE/EMANE emulation target — run the real core as a Linux daemon | Planned | 0 / 3 |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#194](https://github.com/swarm-routing/AntHocNet/issues/194) Make the NS-3 adapter satellite-capable (multi-interface, timescales, non-wifi signals) | Planned | no sub-issues yet |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#302](https://github.com/swarm-routing/AntHocNet/issues/302) secured AntHocNet — attribute-gated trust + authenticated ants, default-off and byte-identical to the paper-faithful path | Planned | no sub-issues yet |
| [AntHocNet](https://github.com/swarm-routing/AntHocNet) | [#564](https://github.com/swarm-routing/AntHocNet/issues/564) Wider threat model (v3.3.0): wormhole, rushing, Sybil and pheromone poisoning | Planned | 0 / 4 |
| [ARA](https://github.com/swarm-routing/ARA) | [#3](https://github.com/swarm-routing/ARA/issues/3) ARA as a standalone hexagonal protocol (Phase 3) | In progress | 2 / 3 |
| [BeeAdHoc](https://github.com/swarm-routing/BeeAdHoc) | [#3](https://github.com/swarm-routing/BeeAdHoc/issues/3) BeeAdHoc as a standalone hexagonal protocol (Phase 4) | In progress | 3 / 7 |
| [HOPNET](https://github.com/swarm-routing/HOPNET) | [#3](https://github.com/swarm-routing/HOPNET/issues/3) HOPNET as a standalone hexagonal protocol (scheduled after Termite) | In progress | 1 / 3 |
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | [#19](https://github.com/swarm-routing/ns3-containers/issues/19) OS and compiler coverage — the platforms ns-3 supports and researchers use | In progress | 2 / 6 |
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | [#36](https://github.com/swarm-routing/ns3-containers/issues/36) image test pipeline — every image built is tested by digest (security, structure, unit, profile, integration, regression, downstream) before any tag moves | In progress | 5 / 9 |
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | [#11](https://github.com/swarm-routing/ns3-containers/issues/11) multi-platform ns3-dev images (linux/amd64 + linux/arm64) with docker buildx | Planned | no sub-issues yet |
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | [#12](https://github.com/swarm-routing/ns3-containers/issues/12) developer documentation for the ns3-dev images (usage, per-image pages, debugging, CI/CD) kept current by AI review | Planned | 0 / 7 |
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | [#27](https://github.com/swarm-routing/ns3-containers/issues/27) security refresh — keep the supported ns-3 release's images patched (scheduled base refresh + scan-triggered rebuilds; older releases on demand) | Planned | 0 / 4 |
| [ns3-swarm-core](https://github.com/swarm-routing/ns3-swarm-core) | [#82](https://github.com/swarm-routing/ns3-swarm-core/issues/82) swarm-core 2.0.0: the host contract, so a protocol core runs on any host | Planned | 0 / 4 |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | [#2](https://github.com/swarm-routing/ns3-tools/issues/2) A protocol-agnostic comparison harness, packaged on its own | In progress | 2 / 8 |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | [#7](https://github.com/swarm-routing/ns3-tools/issues/7) metrics 2026 — age of information, delay percentile/CDF export, energy-per-bit, route lifetime/convergence as CSV metrics | Planned | 0 / 1 |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | [#15](https://github.com/swarm-routing/ns3-tools/issues/15) Comparators: swarm, learned and secure protocols under identical conditions | Planned | 0 / 10 |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | [#34](https://github.com/swarm-routing/ns3-tools/issues/34) promote AntHocNet's vendored comparator modules into ns3/arms/: aomdv, gpsr, qrouting, oracle | Planned | 0 / 2 |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | [#43](https://github.com/swarm-routing/ns3-tools/issues/43) Network substrates: the ns-3 pieces new network types need, for every arm | Planned | 0 / 10 |
| [skills](https://github.com/swarm-routing/skills) | [#9](https://github.com/swarm-routing/skills/issues/9) Protocol-development and org-ops skills: fidelity sheets, invariant review, module scaffolds, anchors, handoffs | In progress | 3 / 11 |
| [swarm-routing.github.io](https://github.com/swarm-routing/swarm-routing.github.io) | [#3](https://github.com/swarm-routing/swarm-routing.github.io/issues/3) Colony Arena: the one org site, built from the protocol repos | In progress | 5 / 7 |
| [swarm-routing.github.io](https://github.com/swarm-routing/swarm-routing.github.io) | [#21](https://github.com/swarm-routing/swarm-routing.github.io/issues/21) Campaign mode: one chapter per network type, with a game UI | Planned | 0 / 2 |
| [swarm-routing.github.io](https://github.com/swarm-routing/swarm-routing.github.io) | [#27](https://github.com/swarm-routing/swarm-routing.github.io/issues/27) Colony Arena polish: navigation, SEO, usability, search | Planned | 0 / 10 |
| [Termite](https://github.com/swarm-routing/Termite) | [#3](https://github.com/swarm-routing/Termite/issues/3) Termite as a standalone hexagonal protocol (Phase 5) | In progress | 1 / 4 |

<!-- epics:end -->

Every implemented protocol is deterministic for a fixed seed and compared by
paired per-seed deltas over ≥ 20 seeds. Licensing follows AntHocNet: each
simulator-free `core/` and the standalone tooling are `MIT OR GPL-2.0-only`;
ns-3 modules, sites, docs and data are `GPL-2.0-only`. Plan: [ROADMAP.md](https://github.com/swarm-routing/.github/blob/main/ROADMAP.md).
Conventions:
[CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md).

Support the work: [sponsor @danieljoppi](https://github.com/sponsors/danieljoppi)
(it keeps the ns-3 images, CI and benchmark campaigns running), or cite
the work: every repository with an archived release has a Zenodo concept DOI (its README's DOI
badge; the list is in [CONTRIBUTING, Archived releases](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#archived-releases)),
AntHocNet's is [10.5281/zenodo.20981979](https://doi.org/10.5281/zenodo.20981979).
