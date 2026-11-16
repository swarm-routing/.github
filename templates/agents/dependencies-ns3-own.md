- **The ns-3 build**: this repository's own ns-3 CI (it does not call
  `reusable-ns3-ci.yml`) builds from the release locks alone, with no
  canary leg on `@main` (maintainer decision on swarm-routing/.github#411). A
  dependency's next release reaches it through org-bot's lock bump PR.
