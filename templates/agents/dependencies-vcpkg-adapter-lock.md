## How this repository gets swarm-core and ns3-tools

- **swarm-core's `core/`**: through vcpkg in manifest mode (swarm-routing/.github#489),
  so CI builds against the published port. `vcpkg.json` depends on `swarm-core`
  and pins its version and port-version with an `overrides` entry;
  `vcpkg-configuration.json` takes the port from
  [swarm-routing/vcpkg-registry](https://github.com/swarm-routing/vcpkg-registry)
  at a `baseline` commit (the port's version and the SHA512 of its release
  asset) and vcpkg's helper ports from the builtin registry.
  `core/CMakeLists.txt` calls `find_package(swarm-core CONFIG REQUIRED)`
  (imported target `swarm::core`); configure it with the vcpkg toolchain,
  `-DCMAKE_TOOLCHAIN_FILE="$VCPKG_ROOT/scripts/buildsystems/vcpkg.cmake"`.
  The core CI job sets vcpkg up with swarm-routing/.github's `setup-vcpkg`
  action (the tool at a pinned commit, the binary cache on the org's GitHub
  Packages NuGet feed; the job needs `packages: write`).
- **Two locks**: `swarm-core.lock` names the swarm-routing/swarm-core release
  `core/` builds on (repository, tag, the commit the tag names, version, and
  the SHA256 of `swarm-core-<ver>.tar.gz` from the release's `SHA256SUMS`);
  the `Makefile` names its tag, `core-deps` (the licence boundary is pinned
  by commit, org rule 2) the commit the tag names.
  `swarm-adapter-ns3.lock` (prefix `ADAPTER_`) names the swarm-routing/swarm-adapter-ns3
  release whose ns-3 module (`swarm-core`, `SwarmRoutingBase`) the ns-3 build
  installs as `contrib/swarm-core`: the adapter release whose own
  `swarm-core.lock` names the same swarm-core release, so `core/` and the
  ns-3 module build on one swarm-core.
- **One version**: the `swarm-core / pin` check (swarm-routing/.github
  `tools/checks/check-swarm-core-pin.py`, vcpkg mode) verifies
  `swarm-core.lock` against the release, that the override pins the lock's
  version, and that the registry baseline is a commit on the registry's
  `main` holding exactly that version and port-version; it reports a newer
  swarm-core release (swarm-routing/.github#586: a warning on a PR or a merge
  group, red on `main` only while org-bot's bump PR is open).
- **Bumping**: never by hand. org-bot's `swarm-core-pin` task opens one PR
  (`org-bot/swarm-core-pin`) that writes `swarm-core.lock` from the new
  release, moves the tag and its commit on every line above, the override,
  and the registry baseline to the registry's `main`, once that `main` holds
  the release (its port PR merged; until then it waits). Its `release-lock`
  task opens the PR (`org-bot/release-lock`) that moves
  `swarm-adapter-ns3.lock` to the adapter release built on
  `swarm-core.lock`'s tag, not the newest one, and holds it while no adapter
  release ships that tag. Between releases nothing moves. With
  swarm-routing/.github checked out next to this repository,
  `python3 -I ../.github/tools/checks/release_lock.py verify swarm-adapter-ns3.lock`
  checks the adapter's lock against its release.
- **The ns-3 canary**: `dependencies` of `reusable-ns3-ci.yml` names release
  tags; `canary-dependencies` names `@main`, one non-blocking leg on push,
  schedule and dispatch, never on a PR (swarm-routing/.github#411). A red
  canary on `main` means the next release of a dependency needs work here.
- **Working against an unreleased swarm-core**: `-DSWARM_CORE_DIR=<checkout>/core`
  builds `core/` on a local checkout instead of the port (development only).
