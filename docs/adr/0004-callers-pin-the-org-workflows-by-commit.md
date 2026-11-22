# 0004. Callers pin the org's reusable workflows and actions by commit

- **Status:** accepted
- **Date:** 2026-11-22
- **Issue:** #716 (maintainer decision 2026-11-22: "pin"); amends golden rule 10

## Context

Golden rule 10 said "callers pin `@main`" (maintainer decision 2026-11-02):
a fix to a reusable workflow reached every caller at once. OpenSSF Scorecard's
Pinned-Dependencies check reads every `uses:` that does not name a full
commit as unpinned. On 2026-11-22, 278 of its 286 warning lines over the 20
public repositories were our own references,
`swarm-routing/.github/.github/{workflows,actions}/...@main`; every
third-party action was already pinned (#716). Those warnings are most of the
482 open code-scanning alerts (#629), and an `@main` reference lets any commit
on this repository's `main` change what a caller runs without a change in the
caller.

The org already pins each repository's org-managed files to one commit of
this repository: `.github/org-sync.lock` (#586), moved only by org-bot's
org-sync refresh PR, which carries the new rendered text with it.

## Decision

1. **Every `uses: swarm-routing/.github/<path>@<ref>` line names a commit**:
   `@<40 hex> # main@<that commit's date>`. In a repository org-sync manages,
   the commit is the one its `.github/org-sync.lock` pins, in the managed
   workflows (rendered so) and in the repository's own workflows and composite
   actions (the `refs` items: only that reference is the org's, the rest of
   the file the repository's).
2. **Only org-sync writes or moves them.** `org_sync.py apply` (org-bot's
   hourly refresh PR) pins the lock and every reference to one commit: the
   newest commit of `main` that changed what renders (`templates/`,
   `tools/org-sync/`, `tools/fidelity/`, `ISSUE_TEMPLATE/`, `LICENSE`) or a
   workflow or action the references name (`content_pin`). A newer commit
   that renders nothing new and changes no referenced workflow moves nothing,
   so it opens no PR (#586); a change to a reusable workflow or action moves
   every caller in one refresh PR each, CI judging it on the pinned commit.
3. **`check / org-sync` fails on any other ref**, `@main` included. The check
   runs the tools at the lock's commit, so the rule starts in each repository
   with the refresh PR that rewrites its references; there is no migration
   window to keep `@main` allowed.
4. **Inside swarm-routing/.github**, a top-level workflow calls its reusable
   workflows and actions by local path (`./.github/...`, the same commit). A
   reusable workflow cannot: in the caller's run a local action path names the
   caller's checkout, so its calls to this repository's actions and workflows
   are full references, pinned by `org_sync.py refs` (org-bot's org-sync task
   for `.github`) to the newest commit that changed them by more than those
   references (`self_pin`), so pinning never chases its own refresh.
5. **Dependabot leaves them alone**: the seeded `.github/dependabot.yml`
   ignores `swarm-routing/.github*`.
6. **The rest of rule 10 stands**: inputs are only added, with
   backward-compatible defaults; a breaking change needs a new file or a tag,
   announced in an issue in every caller.

## Consequences

- Scorecard's Pinned-Dependencies stops flagging the org's own references
  once each repository's refresh PR lands.
- A fix to a reusable workflow reaches a caller when its refresh PR merges
  (hourly, through the merge queue), not at once; a change to a workflow
  another reusable workflow calls takes two refreshes (the fleet moves, then
  `.github`'s own references move, then the fleet again).
- Writing a reference by hand is drift: an agent adds a new call with any ref
  and runs `org_sync.py apply`, or leaves it to the refresh.
- The tools a reusable workflow checks out or downloads at run time
  (`tools/`, `versions.env`, `ruff.toml`) still come from `main`; pinning
  those is a separate change.
- org-sync needs this repository's history to pick the pin; it unshallows
  org-bot's checkout when it must.
