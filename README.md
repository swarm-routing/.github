# swarm-routing/.github

Org-wide defaults for every `swarm-routing` repository.

| Path | Purpose |
|---|---|
| `profile/README.md` | The org profile page |
| `CONTRIBUTING.md` | Invariants, issue body shape and label taxonomy (from AntHocNet's ADR-0013) |
| `ISSUE_TEMPLATE/`, `pull_request_template.md` | Default forms for repos without their own |
| `labels.json` + `.github/workflows/sync-labels.yml` | The label taxonomy and the reusable workflow that applies it to a repo |
| `.clang-format` | LLVM-based C++20 style |
| `.github/workflows/reusable-ns3-ci.yml` | Build + test.py + smoke of a contrib module in `ghcr.io/swarm-routing/ns3-dev`, plus format and SPDX checks |

Adopting the CI in a protocol repo:

```yaml
# .github/workflows/ci.yml
on: { push: { branches: [main] }, pull_request: {} }
permissions: { contents: read, packages: read }
jobs:
  ci:
    uses: swarm-routing/.github/.github/workflows/reusable-ns3-ci.yml@main
    with:
      modules: ara=ns3
      dependencies: swarm-core=swarm-routing/ns3-swarm-core@main
```

Inputs are documented at the top of the workflow file.
