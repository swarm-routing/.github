## How this repository gets swarm-core and ns3-tools

- **swarm-core's `core/`**: `swarm-core.lock` names one swarm-core release
  (repository, tag, the commit the tag names, version, and the SHA256 of
  `swarm-core-<ver>.tar.gz` from the release's `SHA256SUMS`);
  `core/CMakeLists.txt` reads it and fetches the tarball with CMake
  `FetchContent` `URL` + `URL_HASH`. The `Makefile` and the ns-3
  dependency name the lock's tag; `core-deps` (the licence boundary is pinned
  by commit, org rule 2) and a benchmark cell's dependency (its build mode
  takes a commit) name the commit the tag names.
- **Bumping**: never by hand. The `swarm-core / pin` check (swarm-routing/.github
  `tools/checks/check-swarm-core-pin.py`, lock mode) verifies the lock against
  the release and fails when a newer swarm-core release is out; org-bot's
  `swarm-core-pin` task then opens the bump PR (`org-bot/swarm-core-pin`) with
  the lock written from that release. Between releases nothing moves.
  With swarm-routing/.github checked out next to this repository,
  `python3 -I ../.github/tools/checks/release_lock.py verify swarm-core.lock`
  checks it locally.
- **The ns-3 build**: `dependencies` of `reusable-ns3-ci.yml` names release
  tags; `canary-dependencies` names `@main`, one non-blocking leg on push,
  schedule and dispatch, never on a PR (swarm-routing/.github#411). A red
  canary on `main` means the next release of a dependency needs work here.
- **Working against an unreleased swarm-core**: `-DSWARM_CORE_DIR=<checkout>/core`
  builds `core/` on a local checkout instead of the lock (development only).
- **Later**: `find_package(swarm-core CONFIG)` from an installed release, then
  a vcpkg registry (swarm-routing/ns3-swarm-core#135).
