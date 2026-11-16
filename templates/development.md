# Developer guide

<!--
The org's skeleton for docs/development.md (swarm-routing/.github#490). Keep
every `##` heading below, in this order: tools/docs-review/check_docs.py fails
when one is missing. Fill each from what actually runs today (the commands CI
runs, the Makefile, AGENTS.md "Build & verify"); never invent a command. Mark a
step that only CI can run with the workflow that runs it. Write for a person
new to the repository: plain sentences, every command copy-pasteable. A
heading with nothing to say for this repository keeps one sentence saying so.
Delete this comment.
-->

What this repository is in one or two sentences, and what a contributor
usually changes here.

## Prerequisites

The operating system, compiler and C++ standard, CMake, Python, Node,
Docker, emsdk: what this repository needs, each with the version CI uses.

## Get the code

```bash
git clone https://github.com/swarm-routing/REPO.git
cd REPO
```

Submodules, sibling checkouts or forks the work needs.

## Dependencies

Where each dependency comes from: the release locks today (CONTRIBUTING
"Dependencies"), the vcpkg registry once swarm-routing/.github#489 rolls out,
ns-3 through the `ghcr.io/swarm-routing/ns3-dev` images.

## Build

The build, smallest first (a simulator-free `core/` alone, then the ns-3
module in an ns3-dev container, then anything else).

## Test

Every test suite, how to run it locally, and which of them CI runs.

## Run

How to run what the repository produces (an example, the harness, a campaign
cell, the site), with one command that works.

## Docker and dev containers

The images this repository builds or uses, and how to work inside one;
`.devcontainer/` if it has one.

## Lint and format

clang-format, clang-tidy, ruff, licence headers: the commands CI runs.

## CI map

| Workflow | What it checks | Required |
| --- | --- | --- |
| `name.yml` | ... | yes / no |

The required checks are the ones the `main` ruleset lists (`gh api
repos/swarm-routing/REPO/rules/branches/main`).

## Release

How a version is cut: [CONTRIBUTING "Cutting a release"](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#cutting-a-release),
and what a release of this repository publishes.

## Troubleshooting

The failures a newcomer meets, each with its cause and fix.
