## How this repository gets swarm-core and ns3-tools

- **swarm-core's `core/`**: `core/CMakeLists.txt` fetches it with CMake
  `FetchContent` at one commit, `SWARM_CORE_REF`. The `Makefile` and every
  workflow's swarm-core `core-deps` name the same commit; the
  `swarm-core / pin` check (swarm-routing/.github
  `tools/checks/check-swarm-core-pin.py`) fails when they disagree or when
  swarm-core `main` changed `core/` since the pin. org-bot's `swarm-core-pin`
  task then opens the bump PR (`org-bot/swarm-core-pin`), touching only those
  lines; review it and let it merge rather than bumping by hand.
- **The ns-3 build**: the `dependencies` input of
  `reusable-ns3-ci.yml` names the swarm-core and ns3-tools (`routing-bench`)
  refs the module builds on. A ref is a branch or a tag (`@vX.Y.Z`).
- **Working against an unreleased swarm-core**: `-DSWARM_CORE_DIR=<checkout>/core`
  builds `core/` on a local checkout instead of the pin (development only).
- **Next, from swarm-core v0.3.0** (swarm-routing/ns3-swarm-core#134): the
  commit pin becomes a release lock, `swarm-core.lock` (tag, commit and the
  release tarball's SHA256, every value read from the release), fetched by
  `URL` + `URL_HASH`; the ns-3 `dependencies` name release tags and
  `canary-dependencies` names `@main`, a non-blocking leg outside PRs
  (swarm-routing/.github#411). The `protocol-review` check warns about a new
  dependency on a moving ref. Later: `find_package(swarm-core CONFIG)` from
  an installed release, then a vcpkg registry (swarm-routing/ns3-swarm-core#135).
