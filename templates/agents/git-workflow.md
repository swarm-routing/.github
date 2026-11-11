- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`, so it is a lowercase Conventional Commit
  (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR and
  the required checks, not an up-to-date branch. Bots push `bot/<name>` branches
  and open PRs; a release is the bump PR from `bot/release`, tagged after it
  merges (CONTRIBUTING "Cutting a release").
- When a PR falls behind `main`, update it from a checkout of the repo (`gh`
  fills `{owner}` and `{repo}`; set `PR` to the PR number):
  `PR=123; gh api -X PUT "repos/{owner}/{repo}/pulls/$PR/update-branch"`.
  Then merge PRs one at a time, each after its CI on the updated branch. Never force-push a
  branch someone else pushed. A behind `bot/release` PR is the exception:
  dispatch the release `bump` again, so the version and changelog are rebuilt
  on the new `main`.
- **Settings are code.** Repository settings, rulesets, required checks and the
  Actions allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in `swarm-routing/.github`,
  never in the UI or by a direct API write. A `templates/rulesets/` change
  applies on merge; a repo's `[settings]` change applies when `repo-settings`
  in `swarm-routing/.github` is dispatched with mode `apply` after the merge
  (the daily run only checks). A required check runs on every PR (no `paths:`
  filter; skip work inside a gate job instead) and is named exactly as its
  check run. A new third-party action goes into `defaults.json`
  `selected_actions` (`templates/rulesets/`) before or with the workflow that
  uses it: in the same PR in `swarm-routing/.github`, otherwise merged there
  first, or `repo-settings` refuses the repo.
