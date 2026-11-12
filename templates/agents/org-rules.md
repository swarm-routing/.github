1. **Licensing per directory, as AntHocNet**: `core/` and standalone tooling
   are `MIT OR GPL-2.0-only`; ns-3 modules, the site, docs and data are
   `GPL-2.0-only`. Every original source file starts with the org copyright
   line and the SPDX line its directory has in `LICENSING.md`.
2. **The licence boundary only goes one way**: GPL code may use the dual
   parts, never the reverse. A `core/` file includes only the standard
   library, other `core/` files and a pinned dependency's dual `core/`.
3. **Wire formats are POD + versioned**: a leading version byte, bounded
   little-endian readers; a changed field bumps it.
4. **No contrib module named `core`**: the shared module is `swarm-core`.
5. **Determinism**: a fixed `--seed=<N>` gives byte-identical output.
6. **Comparisons are paired**: per-seed deltas over >= 20 seeds; a
   comparator arm counts only after its three gates.
7. **Keep bounded structures bounded**: every queue and history has a cap.
8. **CI hygiene.** Actions pinned by full SHA with a `# vX.Y.Z` comment; a
   `timeout-minutes` on every job and on every apt, npm or installer step;
   `apt-get update --error-on=any` inside a shell retry; transient artifacts
   `retention-days` <= 7; a new third-party action goes into
   `templates/rulesets/defaults.json` `selected_actions` first.
9. **Nothing shipped depends on `.claude/`**: scripts live in `tools/`.

Before you add a file or a directory, touch a `core/` include, a wire
format, randomness, a benchmark comparison or a workflow, read that rule in
full: [org golden rules](https://github.com/swarm-routing/.github/blob/main/docs/agents/org-rules.md);
in a `swarm-routing/.github` checkout next to this repository, that is
`../.github/docs/agents/org-rules.md` (one level up; not this repository's
own `.github/`).
