- **The ns-3 build**: this repository does not call `reusable-ns3-ci.yml`;
  its own CI builds on the versions its pins and locks name and has no canary
  leg on a dependency's `main` (maintainer decision 2026-11-16,
  swarm-routing/.github#411). A change a dependency's next release needs here
  shows when its pin or lock is bumped.
