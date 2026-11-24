## How this repository gets swarm-core

- **swarm-core's `core/`**: this is the ns-3 adapter of swarm-core's ports, with
  no `core/` of its own (swarm-routing/swarm-adapter-ns3#258).
  `swarm-core.lock` at the root names one swarm-routing/swarm-core release
  (repository, tag, the commit the tag names, version, and the SHA256 of
  `swarm-core-<ver>.tar.gz` from the release's `SHA256SUMS`). The root
  `CMakeLists.txt` reads it, fetches the tarball with CMake `FetchContent`
  `URL` + `URL_HASH` and links its `core/` (the target `swarm::core`) PUBLIC,
  so a protocol that links this module gets swarm-core with it. The lock is
  the whole pin: no `core-deps`, no `Makefile` or ns-3 dependency names
  swarm-core here.
- **Bumping**: never by hand. Write the lock with swarm-routing/.github
  `tools/checks/release_lock.py` (`render`, `bump`); org-bot's
  `swarm-core-pin` task opens the bump PR (`org-bot/swarm-core-pin`) that moves
  the lock alone when a newer swarm-core release is out. With
  swarm-routing/.github checked out next to this repository,
  `python3 -I ../.github/tools/checks/release_lock.py verify swarm-core.lock`
  checks the lock against the release, as CI does.
- **Downstream**: protocols build their ns-3 module on this one's release
  tags, and their own `core/` on the swarm-core release their own
  `swarm-core.lock` names; a release here ships its `swarm-core.lock`.
- **Working against an unreleased swarm-core**: `-DSWARM_CORE_DIR=<checkout>/core`
  builds on a local swarm-core checkout instead of the lock (development only;
  nothing committed names it).
