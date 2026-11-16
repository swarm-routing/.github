# 0002. Pipelines are written in Go; their image is distroless

- **Status:** accepted
- **Date:** 2026-11-16
- **Issue:** #531 (the migration epic)

## Context

Every pipeline in the org (the code a workflow runs: licence and DCO gates,
the review gate, org-sync, org-bot, repository settings, Zenodo, releases) is
a stdlib Python script under `tools/`, about 28 000 lines over twenty
scripts, each run by `python3 -I` on a fresh runner (inventory: #531). That
has served, but the costs grow with the code:

- **No types, late failures.** A renamed key or a `None` where a dict was
  expected fails at run time, often only on the branch a fixture did not
  reach, and often in a bot run nobody watches.
- **The interpreter is the environment.** Each job depends on the runner's
  Python; a script cannot be pinned and shipped as one artifact, so "the
  version that was tested" is a commit plus whatever `python3` the runner had.
- **Big single files.** The largest tools are 2 000–2 700-line scripts,
  because a stdlib script that must run with `python3 -I` from a checkout
  cannot easily be split into a package.

The maintainer decided (2026-11-16) that pipelines move to Go, and how Go
runs in Actions and in images. This ADR records it.

## Decision

### The language rule

1. **Pipelines are written in Go.** A pipeline is code a workflow runs: a
   check, a gate, a bot task, a release step. Python is used for a pipeline
   only when no reasonable Go option exists (a library with no Go
   equivalent), and the PR says why.
2. **Skill scripts stay Python by default.** A skill's script (the
   `swarm-routing/skills` procedures, `lit_search.py`,
   `check_invariants.py`) may stay Python; a skill may call a Go tool when
   the work is one a pipeline already does.
3. **swarm-routing/ns3-tools stays Python + C++.** Its readers and statistics
   are a research CLI, published to PyPI, used outside the org's pipelines.
4. **Existing Python pipelines migrate gradually, never in bulk** (#531):
   one tool per PR, each port proving **byte-identical output** with the
   Python version on the same fixtures (stdout, stderr, exit code and every
   file written), the workflow switched only after the port merges, the
   Python script deleted after one green run on the Go tool.

### Go conventions

- **Module path** `github.com/swarm-routing/<repo>` (here
  `github.com/swarm-routing/.github`); a `go.mod` with a `go` line and a
  `toolchain` line naming one released Go version. The `toolchain` line is
  the version CI and the image build use.
- **Layout:** one command per directory under `cmd/<tool>/` (package `main`,
  thin: flags, then a call into `internal/`), the logic in `internal/<pkg>/`,
  fixtures in `testdata/` beside the test that reads them. No `pkg/`: nothing
  here is a library for other modules.
- **The self-test is `go test`.** What a Python tool's `--self-test` does
  against fixtures and a fake GitHub is a Go test against `testdata/` and an
  `httptest` server; `go test ./...` runs them all.
- **The golden rules apply.** Determinism wherever output is read or
  compared (sorted map iteration, no wall clock in an output, injected time
  and randomness, byte-identical reruns); bounded structures (every queue,
  cache and retry loop carries a cap); licence headers as C++ (`//` comments;
  `tools/` and `cmd/`/`internal/` of a tooling repository are
  `MIT OR GPL-2.0-only`), checked by `tools/checks/check-headers.py`.
- **Dependencies:** standard library first; a third-party module only with a
  reason in the PR, pinned in `go.sum`, scanned by govulncheck.

### Running Go in Actions

- **No container for building and testing.** `actions/setup-go` pinned by
  SHA, the version read from `go.mod`'s `toolchain` line, `GOTOOLCHAIN=local`
  (no silent toolchain download), setup-go's module and build cache.
- **Builds are `CGO_ENABLED=0 go build -trimpath`**: static, reproducible,
  no host paths in the binary. Only the race-detector test run enables cgo,
  for the test binaries, which are never shipped.
- **The checks** are `.github/workflows/reusable-go-ci.yml`: build, gofmt,
  go vet, staticcheck, govulncheck, `go test -race` with coverage
  (report-only; the Go profile for SonarQube Cloud, Cobertura for Codecov),
  proven by `go-ci-selftest.yml` on a passing and a failing fixture module.

### The image rule

When a Go tool runs from an image, the image is:

- **multi-stage**: built on the official `golang:<stable>` image, pinned by
  digest, at the `toolchain` version; the runtime stage is
  `gcr.io/distroless/static-debian12:nonroot`, pinned by digest. Not Alpine:
  with cgo off, musl brings nothing, and a shell and `apk` in the runtime
  image are attack surface with no use. Every `cmd/<tool>` is compiled
  `CGO_ENABLED=0 -trimpath` in the build stage, with the Go tests run there
  too, and copied as `/usr/local/bin/<tool>`.
- **under the same supply-chain gates as the `ns3-dev` images**: hadolint,
  Trivy (configuration and the image's vulnerabilities), a CycloneDX SBOM,
  a keyless signature and a build-provenance attestation, base images pinned
  by digest and kept current by an update bot.

The org's image is **`ghcr.io/swarm-routing/ci-tools`**, built from this
repository's `cmd/`:

- **ENTRYPOINT is a small dispatcher**, `ci-tools <tool> [args…]`, which
  executes `/usr/local/bin/<tool>`; each tool is also its own binary at that
  path. Distroless has no shell, so nothing else runs there.
- **Workflows run a tool with `uses: docker://ghcr.io/swarm-routing/ci-tools@sha256:<digest>`**
  and `with: args: <tool> …`: no toolchain and no shell in the job, the
  workspace mounted as GitHub mounts it for every container action.
- **What is tested is what is tagged** (swarm-routing/ns3-containers golden
  rule 17): a change to the Go code or the image builds the image once,
  pushes it as a candidate to `ghcr.io/swarm-routing/ci-tools-dev`, checks
  that the pushed digest is the image it tested, and runs the image's tests
  and the tools' self-tests on that digest. On `main` the same digest is
  promoted to `ci-tools` by a registry copy (no rebuild), then signed and
  attested; pull requests never promote. Candidates are swept by
  `reusable-dev-image-cleanup.yml` (the `-dev` package's 2-day retention).
- **Workflows pin the image by digest**, never a tag. After a publish, an
  org-bot task opens the digest-bump PR, as it does for the release locks.
- Static binaries with checksums may also be attached to a release, for a
  job where an image pull is slower than a download; that is an option, not
  part of the rule.

## Alternatives considered

- **Stay in Python, add types (mypy) and packaging.** Removes some late
  failures, keeps the interpreter as the environment, adds a type checker and
  a packaging step to every tool; the scripts stay one runtime away from a
  pinned artifact. Rejected as the long-term answer; it remains the rule for
  skill scripts and ns3-tools.
- **Rust.** Static binaries and strong types too, but long compile times
  in CI for small tools, a steeper curve for contributors who also write C++
  and Python here, and more ceremony for the HTTP-and-text work the
  pipelines are. Rejected: Go gives the same static artifact for less.
- **TypeScript (JavaScript actions).** The native shape of an Action, but a
  Node runtime and an `npm` dependency tree in every tool, bundled `dist/`
  files to review, and a supply chain larger than the tools themselves.
  Rejected.
- **C++.** Already the org's simulation language, but no standard HTTP or
  JSON, and a build system per tool. Rejected for pipelines; C++ stays where
  it is (the cores and ns-3 modules).
- **Go in a container job** (`container: golang:…`) instead of setup-go.
  Slower start, the cache harder to share, and nothing gained over a
  pinned setup-go for building and testing. Rejected; containers are for
  running the shipped tools.
- **Alpine runtime image.** Smaller than a Debian base, but carries a shell
  and a package manager; with static Go binaries distroless static is
  smaller still and has neither. Rejected.

## Consequences

- New pipeline code is Go from now; a Python pipeline PR must name why no
  reasonable Go option exists.
- Contributors need Go (the `toolchain` version) for pipeline work; skills
  and ns3-tools do not change.
- Each tool moved to Go becomes a pinned, signed artifact, so a workflow runs
  exactly what was tested; the price is a digest bump PR per tool change,
  which org-bot opens.
- The migration is long and incremental (#531); until it ends, both Python
  and Go pipelines exist, and the byte-identical rule keeps each switch
  invisible to the repositories that call them.
- The `ci-tools` package must be public for other repositories' workflows to
  pull it without credentials; package visibility is a GitHub setting.
