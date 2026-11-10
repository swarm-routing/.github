- Branch from `main` (`claude/<short-topic>`), one focused change per PR.
- **Always open a PR to `main`** once the branch is pushed — every change is
  tracked through one.
- **PRs are squash-merged** (the only merge method enabled). The PR title is
  the commit on `main`, so it is a lowercase Conventional Commit
  (`feat:`/`fix:`/`docs:`/`chore:`/`ci:`…, optional scope).
- Push with `git push -u origin <branch>`; merge when CI is green.
- **`main` takes no direct push**, in any repo: its ruleset requires a PR, an
  up-to-date branch and the required checks. Bots push `bot/<name>` branches
  and open PRs; a release is the bump PR from `bot/release`, tagged after it
  merges (CONTRIBUTING "Cutting a release").
- When a PR falls behind `main`, update it
  (`gh api -X PUT repos/<owner>/<repo>/pulls/<n>/update-branch`) and merge PRs
  one at a time, each after its CI on the updated branch. Never force-push a
  branch someone else pushed.
- **Settings are code.** Repository settings, rulesets, required checks and the
  Actions allowlist change only by a PR to the repo's `[settings]` in
  `.github/org-sync.toml` or to `templates/rulesets/` in `swarm-routing/.github`,
  never in the UI or by a direct API write. A required check runs on every PR
  (no `paths:` filter; skip work inside a gate job instead) and is named exactly
  as its check run. A new third-party action goes into `defaults.json`
  `selected_actions` in the same change, or `repo-settings` refuses the repo.
