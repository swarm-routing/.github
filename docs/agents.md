# Agent tooling: MCP servers, plugins and token habits

The org standard for what an AI agent session runs and how it keeps its
context small. The decision and its measurements are
[ADR-0005](adr/0005-the-mcp-and-agent-tooling-standard.md); this page is the
short form. Every repository's AGENTS.md links it from "Session habits".

## MCP servers

| Server | Status | How it reaches a session |
|---|---|---|
| `swarm-mcp` (read-only verdicts of the org scripts; its own repository, [swarm-routing/swarm-mcp](https://github.com/swarm-routing/swarm-mcp), released on its own; swarm-routing/skills#185) | standard, once released | bundled in the `swarm-routing` plugin (swarm-routing/skills), which will pin a swarm-mcp release once the code has moved, and which every repository's committed `.claude/settings.json` enables |
| GitHub's MCP server | standard where the host provides it (hosted sessions) | the host; in a local session, GitHub's own server with `--read-only` unless the task writes, or the `gh` CLI |
| `clangd-lsp`, `gopls-lsp`, `pyright-lsp` (Claude Code's official LSP plugins) | optional, local terminal sessions only (cloud sessions do not start language servers); swarm-routing/skills#175 measures them | a person installs the plugin and the language server; never a committed setting |
| Obsidian or any notes vault, Serena, third-party clangd bridges, code-graph indexes, repo packers, hosted MCP endpoints | ruled out (ADR-0005, Decision 3) | — |

Rules for any server:

- It arrives only through the plugin or a committed `.mcp.json`, by a
  reviewed PR. No skill installs or configures one (skills golden rule 10).
- Local, stdio, pinned by version or digest, no account, nothing sent
  anywhere but the model. No `_meta["anthropic/alwaysLoad"]`: its tools stay
  deferred until used.
- Its PR states its effect, measured with `token_audit.py` (below).

## Habits that save the most

In the order the 2026-11-22 audit ranked them:

1. **Attach only the repositories the task needs.** Each attached repository's
   agent files cost 8,000 to 13,000 tokens on every request of the session and
   of every subagent. In the audited session (13 repositories attached,
   measured with `token_audit.py`), the agent files were about 114,000 of
   the 141,050 tokens of its first request (81 %), carried on each of its
   5,675 requests (about 2.49 billion tokens read from cache in all).
2. **Start the session inside a repository folder.** The `swarm-routing`
   plugin, and with it swarm-mcp, the `org-worker` agent and the skills,
   loads only from the `.claude/settings.json` of the folder the session
   starts in. A hosted session with several repositories that starts in
   their parent folder (`/home/user`) reads none, so it has no swarm-mcp
   tools and no `org-worker`, as the audited session had none. Start in the
   repository the task is about; check that the session lists the
   `swarm-routing` skills before relying on them.
3. **Delegate single-repository work to a worker that skips the others'
   agent files** (`omitClaudeMd: true`; the `org-worker` agent,
   swarm-routing/skills#186), and read-only searches to the built-in Explore
   agent, which skips them too.
4. **Search large outputs, never read them whole**: an output the harness
   saved to a file goes through `grep`, `head`, `sed -n` or a section reader
   (#286). Wait on a PR with `tools/pr-status/pr_status.py`, not by
   subscribing to its activity (below; #794).
5. **Run the script, read its verdict** (AntHocNet ADR-0014; #286 adds the
   issue index and readers).
6. **Keep agent files under their budget**: `check_docs.py` fails an
   AGENTS.md whose org-sync sections pass 23,200 B, and its self-test fails a
   template PR that would (#793). A template PR states its byte delta
   (`token_audit.py files` before and after).
7. **A coordinator's state lives on its handoff issue, never a local file**
   (#1009): each pass is `tools/issues/handoff.py append REPO#N --status
   FILE ...` (FILE: `tools/status/status.py --json`), a marked comment in a
   fixed shape (Closed, Released, Running workers, Maintainer items,
   Scheduled) that also replaces the issue body's state section; a new
   session starts from `handoff.py read REPO#N`. A local `ROADMAP_STATE.md`
   was lost with its container and re-posted to #921 by hand.

## Large outputs and PR waits (#794)

Every tool result stays in the context for the rest of the conversation and
is re-read from cache on every later request. Two sources dominated the
audited orchestrating session of 2026-11-22 (`token_audit.py transcript`,
main transcript, measured):

| Source | Calls | Result bytes | Per call |
|---|---:|---:|---:|
| `Read` of an output the harness had saved to a file | 21 | 4,036,452 (36 %) | ≈ 192,000; the largest 655,082 |
| `ReadNotifications` (subscribed PR activity) | 152 | 1,517,535 (13 %) | ≈ 9,980 |

**A saved output:** when a result is too large to show, the harness writes
it to a file and says where. Search that file (`grep -n PATTERN`, `head -n`,
`sed -n 'A,Bp'`, `tail`); never `Read` it whole. Better still, make the
command print less in the first place (a summary flag, `--jq`, a filter).

**Waiting on a PR:** poll with `pr_status.py`, do not subscribe.

| Way to wait (one PR: CI, review, queue, merge) | Result bytes |
|---|---:|
| Subscription (`subscribe_pr_activity`, then `ReadNotifications`): every event, review-bot comments relayed whole, again on each edit | ≈ 9,980 per read (measured above); #801's two bot comments alone (a CodeRabbit rate-limit note, Sonar's gate) are 6,908 B before any edit |
| `pr_status.py wait REPO#N` (CI done), `threads REPO#N`, `queued REPO#N`, `wait --merged REPO#N`: #801 from push to merge, measured 2026-11-22 | 179 + 22 + 110 + 27 = 338 in total |

- `wait REPO#N` polls until no check is pending and prints one line per PR
  (`ci=`, `merge=`, `threads=`); `--review` also waits for CodeRabbit.
- `threads REPO#N` prints each unresolved review thread as one line
  (severity, title from CodeRabbit's headings, path:line, comment id); read
  the full comment only for the thread you are fixing.
- `queued REPO#N` says whether the PR is in the merge queue and how its
  queue runs stand; `wait --merged REPO#N` returns when it merged, or stops
  at the first thing that needs a hand (an unresolved thread, a failed
  required check, auto-merge off).

Subscribe only when the session has nothing else to do for hours and expects
a human reviewer, and the PR has no review bot: an active review bot makes a
subscription the most expensive way to wait.

## Measure

```bash
# what a session loads, per repository and with all of them attached (estimate)
python3 -I ../skills/tools/token-audit/token_audit.py files . ../ARA ../AntHocNet
# where a finished session's tokens went (measured usage; sizes only, no content)
python3 -I ../skills/tools/token-audit/token_audit.py transcript ~/.claude/projects/<dir>/<session>.jsonl
```

Compare a task with and without the change: the first request's context, the
totals, and the calls and bytes per tool.

## Agent pitfalls in full

Every repository's AGENTS.md states each pitfall in one or two sentences
(`templates/agents/agent-defaults.md`, kept under its budget, #793). This is
the long form each line was shortened from on 2026-11-22, with the detail and
the story; CONTRIBUTING holds the procedures it names.

- **Before every push, run the repository's `make check`** (where it has
  none, the commands of its "Build & verify" section; `make pre-push
  TITLE='…'` where the Makefile has it) **and check the PR title** is a
  lowercase Conventional Commit, `type(scope)!: subject` with the type one
  of `feat fix docs style refactor perf test build ci chore revert` and a
  subject that starts lowercase. A check that goes red because a step was
  skipped costs a whole CI round (swarm-routing/.github#586). Never add
  commits to an unrelated PR to re-apply org-sync or fix template drift:
  each repository is checked at the template commit its
  `.github/org-sync.lock` pins, and org-bot's refresh PR moves the pin and
  the text together.
- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- Edit files with the editor tools, never a shell heredoc or `sed -i`, and
  touch one repository per command: the permission system refuses the
  others (swarm-routing/.github#578).
- Stage files by name, never `git add -A`, and keep build output in
  `.gitignore` (`build/core-local/` reached three repositories,
  swarm-routing/.github#644).
- A Go test reads only files under `cmd/` or `internal/` (`testdata/`):
  the image build sees nothing else (swarm-routing/.github#587).
- Clean up only your own directory, never a shared one
  (swarm-routing/.github#644).
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- In an issue, PR or comment, write every issue of another repository in
  full, `swarm-routing/<repo>#N`, also inside a list or a range. A bare `#N`
  links to the repository the text is in: in
  `swarm-routing/AntHocNet#65, #151` the second number points at this
  repository's #151 (swarm-routing/.github#277). An ns-3 item on GitHub is
  its full GitLab URL (or a link whose text is `nsnam/ns-3-dev#N`); in
  anything bound for ns-3's GitLab, an item of ours is its full GitHub URL,
  never `swarm-routing/<repo>#N` or a bare `#N` / `!N` (CONTRIBUTING "ns-3
  bugs (RCAPA)").
- A sentence in `ROADMAP.md` or an AGENTS.md that calls an issue done is not
  evidence: read the issue's acceptance criteria. On 2026-11-12 nine issues
  described as done had open criteria (swarm-routing/.github#274).
- Change text inside `org-sync:begin/end` markers only through the template
  in `swarm-routing/.github` `templates/`: one PR there, then org-bot's
  `bot/org-sync` refresh PR in each repository. A hand edit per repository
  stays red on `check / org-sync` (swarm-routing/.github#236).
- In a repository with a merge queue, merge by enabling auto-merge (squash);
  a direct merge (`PUT pulls/<n>/merge`) is refused with HTTP 405. Only the
  required checks (`gh api 'repos/{owner}/{repo}/rules/branches/main'`, which
  `gh` fills from the checkout) gate a merge: a red or pending report-only
  check (`codecov/patch`, Sonar) is triaged, not waited on. `dco` (not
  required, `pull_request` only) passes at once on a member's, an agent's or
  the org bot's PR (swarm-routing/.github#586); merge an outside
  contributor's PR only after `dco` passed on the head that merges, and
  never push to it: ask them, or follow up after the merge
  (swarm-routing/.github#288). A maintainer who must push to it first
  disables auto-merge or removes it from the queue, and re-enables only
  after `dco` passed on the new head.
- `review / coderabbit` is a required check (the review gate,
  swarm-routing/.github#294): it passes once CodeRabbit has reviewed the PR,
  once it says it will not, for a draft, or 30 minutes after the PR opened
  (then with one comment). So auto-merge may be enabled at once: the merge
  waits for the gate, and the ruleset holds it while a CodeRabbit thread is
  unresolved. Still read every thread and fix or answer it before resolving;
  call a PR free of threads only after CodeRabbit has posted and
  `pulls/N/comments` and the reviews show none
  (swarm-routing/ns3-upstream-report#41).
  Where the gate is not required yet (`gh api
  'repos/{owner}/{repo}/rules/branches/main'` does not list it), wait first
  with `python3 -I ../.github/tools/pr-status/pr_status.py gate REPO#N`,
  which waits for CodeRabbit alone (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else: a
  DCO sign-off is a person's own certification (CONTRIBUTING "Outside
  contributions").
- Leave a stale branch (a closed PR's head, a validation branch, a
  superseded bot branch) to org-bot's daily `branch-sweep`, which deletes it
  once its PR has been closed for 2 days, or after 7 days without a commit
  for a `claude/*` or `org-bot/*` branch that never had a PR
  (swarm-routing/.github#595). Agent sessions cannot delete branches; never
  ask the maintainer to delete one.
- Releases are cut on request only: dispatch the release `bump` when the
  maintainer asks, once the version's `release:vX.Y.Z` issues are done and
  its exit criteria in the ladder (`docs/roadmap.md`, or the org ROADMAP's
  release train until it lands) are met; never approve a gated publish. A
  failed publish is recovered with "Re-run all jobs", never "Re-run failed
  jobs" (CONTRIBUTING "Cutting a release"). Never type a release's DOI: read
  it from Zenodo. A public repository's release reaches the site by itself:
  a `[release-sync] <repo> <tag>` issue opens in
  `swarm-routing/swarm-routing.github.io` and a `release-sync.yml` run named
  `Release sync swarm-routing/<repo> <tag>` ends green. If, an hour after
  the release, either is missing, org-bot's hourly `release-sync-watch`
  dispatches that run again within the next hour (swarm-routing/.github#571;
  CONTRIBUTING "Cutting a release"); never dispatch it by hand, and the
  site's weekly Monday run is only the backstop.
- Cite a paper in a public issue, PR or doc by its `https://doi.org/<DOI>`
  link, read from its record (`lit-search` confirms it), or, for a work with
  no DOI, by its publisher's or institution's page; never point into or name
  the private paper library there.
- Never dismiss a security alert, and never rotate or handle a leaked
  secret: both are the maintainer's. Every open alert has a `security`
  ticket kept by the hourly `security-alerts` task (P1 past its SLA), and
  `security-autofix.yml` opens a test-first fix PR for a code finding and a
  proposal for a policy finding (swarm-routing/.github#629); review its PR
  like any other (CONTRIBUTING "Security alerts").
- An ns-3 bug, or an investigation of one, always gets an RCAPA ticket in
  swarm-routing/sim-tools first (form *ns-3 bug (RCAPA)*, labels `rcapa` and
  `ns3-upstream`, ID `NS3-NNN`); its doc in `docs/ns3-rcapa/` and its
  `docs/ns3-bugs.md` row follow, and every workaround links the ID. Upstream
  reports go out only through swarm-routing/ns3-upstream-report (CONTRIBUTING
  "ns-3 bugs (RCAPA)"). A regression in a published library, a version
  another project consumes (a swarm-core or ns3-tools release through its
  lock, PyPI, a vcpkg port), gets an RCAPA too, in that library's repository,
  even when a consumer finds it: ticket first (form *Regression in a release (RCAPA)*,
  `<PREFIX>-NNN`), then `docs/rcapa/rcapa-<name>.md` and its row in
  `docs/rcapa/README.md`; the ticket stays open until a release carries the
  fix. A Docker image gets one only when its composition is the cause.
  None for a bug that never reached a published version, for changes in
  .github, the site, skills, benchmarks or ns3-upstream-report, or for a
  typo with no behaviour; the pins and `git tag --contains <commit>` decide,
  never memory (CONTRIBUTING "RCAPA").

## Detail cut from the other org sections (#793)

The rules stay in every AGENTS.md; these sentences, cut for size, are their
detail.

- **Conventions:** the shared release labels are `release:v0.1.0` to
  `release:v0.4.0` and `release:v1.0.0`; `.github`'s `labels` workflow applies
  `labels.json` to every repository, private ones included. An issue change
  that moves the epic lists is an `epic` label, an epic opened, edited,
  closed or reopened, or a sub-issue closed or reopened; `epics-changed.yml`
  asks `.github`'s `epics-refresh`, debounced, plus hourly for a sub-issue
  added or removed. "Make minimal, reviewable changes; update the relevant
  doc/ADR when you change a documented decision" is now part of *Surgical
  diffs* (Working defaults).
- **Git workflow:** the PR-title rule (type list, lowercase subject) lives
  here once; the pre-push pitfall points to it. A `[settings]` change's push
  runs `settings-apply.yml`, which asks `repo-settings` in
  `swarm-routing/.github` to apply that one repository; the daily run only
  checks, a manual `apply` dispatch is the fallback. A new third-party action
  goes into `defaults.json` in the same `swarm-routing/.github` PR as the
  workflow that uses it, otherwise merged there first.
- **Agent skills:** each skill's own description carries what its table row
  no longer does (`references`: Crossref, DataCite or Zenodo, DOI links first,
  the fidelity Sources table and CITATION.cff references generated;
  `pr-shepherd`: each finding verified and fixed or answered, auto-merge where
  there is a merge queue; `dependency-bump`: the places that name the release
  and the `swarm-core / pin` check, org-bot's bump PR first; `release`: the
  ladder row, dry-run, bump, merge, the Zenodo DOI, the site, consumers'
  locks, the vcpkg port, PyPI; `sonar-triage`: recorded where the quality gate
  reads it, never by exclusion or in the UI). Some hosted sessions with several
  repositories do not read a repository's settings. The section is managed by
  org-sync: a new row goes into `templates/agents/skills.md`, never into a
  repository's AGENTS.md (an edit there is undone by the next
  `org_sync.py apply`).
- **Response style:** the carve-out keeps byte-for-byte exact code, commands,
  file paths, error text and benchmark numbers, and keeps commit messages, PR
  bodies, ADRs, `docs/` and issue / finding threads detailed, because
  cross-session traceability depends on them.
