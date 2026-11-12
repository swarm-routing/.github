- Branch from `main`, one focused change per PR, and open the PR as soon as
  the branch is pushed. PRs are squash-merged; the title is the commit on
  `main`, a lowercase Conventional Commit (`feat:`, `fix:`, `docs:`…).
- `main` takes no direct push. Merge when the required checks are green; in
  a repository with a merge queue, by enabling auto-merge.
- Settings are code: change them only by a PR to `.github/org-sync.toml`
  `[settings]` or `templates/rulesets/` in `swarm-routing/.github`.

Before you push, update a PR that is behind `main`, merge, or change a
setting, read [the git workflow in full](https://github.com/swarm-routing/.github/blob/main/docs/agents/git-workflow.md).
