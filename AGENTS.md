# AGENTS.md — guide for AI coding agents

Operational guide for LLM agents working in `swarm-routing/.github`. Read this
before changing anything. Org-wide conventions:
[`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md). Shape and rules mirror
[AntHocNet's AGENTS.md](https://github.com/swarm-routing/AntHocNet/blob/main/AGENTS.md), the source repository.

## What this repo is

Org-wide defaults for every `swarm-routing` repository: the profile page,
default issue forms and PR template, the label taxonomy, the C++ style, and the
reusable workflows other repos call (`reusable-ns3-ci.yml`, `reusable-ns3-image.yml`,
`reusable-release.yml`, `reusable-benchmark-cell.yml`, `sync-labels.yml`).
Files here only take effect from `main` (GitHub reads community defaults and
`@main` workflow references from the default branch).

```
profile/README.md, ROADMAP.md, CONTRIBUTING.md   the org landing page, its phases, its invariants and conventions
ISSUE_TEMPLATE/, pull_request_template.md, labels.json   the default forms and the label taxonomy
SECURITY.md, CODE_OF_CONDUCT.md, SUPPORT.md, DCO, .github/FUNDING.yml   the org default community files
.clang-format, ruff.toml           the C++ style and the Python lint baseline
tools/<tool>/                       the org's scripts, each with --self-test (checks, org-sync, org-bot, epics, zenodo, docs-review, fidelity, protocol-review, pr-status, lit-search, repo-settings, release)
templates/                          what org-sync renders into each repository; templates/rulesets/: the settings profiles
.github/workflows/, .github/actions/   the reusable workflows other repos call, this repo's CI and bots, the bot token
docs/                               tools.md (every file, tool, workflow and self-test), where-to-look.md (the full task table)
```

Before adding, changing or running a tool or a workflow, read
[`docs/tools.md`](docs/tools.md): one line per file and directory, every
self-test and read-only run, and how a reusable workflow change is proven.

## Build & verify

No build. Before pushing:

```bash
pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1   # once, as ci.yml
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
python3 -I tools/checks/check-headers.py --self-test && python3 -I tools/checks/check-headers.py --dual '' .
# and the --self-test of every tool you changed: the exact commands are in docs/tools.md
pip install ruff==0.17.1 && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml
```

Every tool has a `--self-test` against fixtures or a fake GitHub, and most a
read-only run against the real org; [`docs/tools.md`](docs/tools.md#self-tests-and-read-only-runs)
lists each with what it covers. A change to a reusable workflow is proven by
its self-test workflow and then by a caller: read
[`docs/tools.md`](docs/tools.md#validating-a-change-to-a-reusable-workflow)
before changing one.

## Golden rules (invariants — do not break)

Org-wide (1–9), then this repo's own.

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
8. **CI hygiene.** Actions pinned by full SHA, a `timeout-minutes` on every
   job and installer step, artifacts kept <= 7 days.
9. **Nothing shipped depends on `.claude/`**: scripts live in `tools/`.

Before you add a file or a directory, touch a `core/` include, a wire
format, randomness, a benchmark comparison or a workflow, read that rule in
full: [org golden rules](https://github.com/swarm-routing/.github/blob/main/docs/agents/org-rules.md).

10. **Reusable workflows are a public contract.** Callers pin `@main`: never rename or remove an input, never change a default's meaning; add inputs with backward-compatible defaults. A breaking change needs a new file or a tag, announced in an issue in every caller repo.
11. **`labels.json` is the taxonomy.** Change it together with `CONTRIBUTING.md` and the issue forms; `sync-labels` never deletes labels, so a rename is a manual migration recorded in an issue.
12. **The issue forms stay AntHocNet's shape.** Same fields, same body sections; org-specific additions only (areas, Depends on, literature).

## Conventions

- An issue has one type label, its area label(s), one `priority:P1|P2|P3`
  (not on epics) and a `release:vX.Y.Z` label only when a release gates it.
  Body: **Context** · **Scope** · **Acceptance criteria** (checkboxes) ·
  **Depends on** · **References**. A child of an epic says "Part of #N" and
  is linked as a sub-issue.
- Comments you post end with the Claude Code footer.
- A generated epic list is never edited by hand: refresh it with
  `swarm-routing/.github` `tools/epics/epics.py`.

Before you file, close or re-scope an issue or an epic, read
[the conventions in full](https://github.com/swarm-routing/.github/blob/main/docs/agents/conventions.md).

## Git workflow

- Branch from `main`, one focused change per PR, and open the PR as soon as
  the branch is pushed. PRs are squash-merged; the title is the commit on
  `main`, a lowercase Conventional Commit (`feat:`, `fix:`, `docs:`…).
- `main` takes no direct push. Merge when the required checks are green; in
  a repository with a merge queue, by enabling auto-merge.
- Settings are code: change them only by a PR to `.github/org-sync.toml`
  `[settings]` or `templates/rulesets/` in `swarm-routing/.github`.

Before you push, update a PR that is behind `main`, merge, or change a
setting, read [the git workflow in full](https://github.com/swarm-routing/.github/blob/main/docs/agents/git-workflow.md).

## Working defaults

Condensed from [andrej-karpathy-skills](https://github.com/forrestchang/andrej-karpathy-skills).

- **Assumptions:** state the ones that matter. Ask only when the choice
  belongs to the maintainer: a default, a published number, a cell, the scope.
  Otherwise pick the sensible option, say which, and keep going. Long
  unattended runs, like campaigns, depend on that.
- **Simplicity:** the least code that solves the task. No speculative
  features, configurability or abstractions for one use.
- **Surgical diffs:** every changed line traces to the request. Match the
  surrounding style. Mention unrelated dead code rather than deleting it, and
  remove only the orphans your own change created.
- **Verifiable goals:** a bug gets a reproducing test first; a refactor passes
  before and after. Finish when the check passes, not when the code looks right.

## Session habits

- **Handoffs are always a ticket.** When a session ends with work in flight, or a
  handoff is asked for, open a GitHub issue from the *Handoff* template (label
  `handoff`). Never write a handoff file in the repo. Start a new session from
  the newest open `handoff` issue, and close it when the work it hands off is
  done ([AntHocNet ADR-0013](https://github.com/swarm-routing/AntHocNet/blob/main/docs/adr/0013-track-bugs-and-findings-as-issues.md) item 5).
- **Attach only the repositories the task needs.** Each attached repository's
  agent files are loaded into every request, whether the task touches it or
  not.
- **Start from the record, not from memory:** the newest open `handoff` issue,
  then the issue's acceptance criteria, then `main`. Check a claim against its
  source before it goes into an issue or a PR.
- **Script what repeats.** A check or a lookup run more than a few times
  becomes a script in `tools/` that prints a summary; the model reads the
  verdict, not the raw data (AntHocNet ADR-0014).
- **Measure before cutting or adding agent text:** the `token-audit` skill
  (`swarm-routing/skills` `tools/token-audit/token_audit.py`) prints what a
  session loads and where a finished session's tokens went.

## Response style — caveman (token economy)

Answer in tight, low-filler prose: drop hedging, pleasantries, and preamble; keep
the substance. Fewer output tokens on every reply, same information.

**Carve-out (the record stays full).** Keep byte-for-byte exact — code,
commands, file paths, error text, benchmark numbers. And keep the *durable
record* detailed, never terse: commit messages, PR bodies, ADRs, `docs/`, and
issue / finding threads. Cross-session traceability depends on those being
complete — AntHocNet's AC_BE_NQOS / A2 investigation was only recoverable
because the issue threads were thorough. Caveman the chat, not the record.

## Agent pitfalls

- `gh api … -F body=@file` reads the file; `-f body=@file` posts the literal
  text `@file`.
- When the permission system refuses a command (a merge, say), stop and report
  it. Never retry it another way, and never ask another agent to run it.
- A PR body's `Closes #N` closes the issue on merge; write `Part of #N` while
  acceptance criteria remain open.
- Before saying a tool or check is missing, look at `main` (`git fetch`,
  `origin/main`), not a stale local checkout.
- In an issue, PR or comment, write every issue of another repository in
  full, `swarm-routing/<repo>#N`, also inside a list or a range. A bare `#N`
  links to the repository the text is in: in
  `swarm-routing/AntHocNet#65, #151` the second number points at this
  repository's #151 (swarm-routing/.github#277).
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
  check (`codecov/patch`, Sonar) is triaged, not waited on. A red `dco` on an
  outside contributor's commit still holds the PR until that author signs
  off; on the maintainer's or an agent's commits it is expected
  (swarm-routing/.github#212). `dco` is not a required check and runs on
  `pull_request` only, so merge an outside contributor's PR, by auto-merge or
  directly, only after `dco` passed on the head commit that merges, and
  disable auto-merge before anyone pushes to that PR.
- Enable auto-merge only after CodeRabbit has reviewed and its threads are
  resolved: it is not a required check, so auto-merge does not wait for it.
  `python3 -I ../.github/tools/pr-status/pr_status.py wait --review REPO#N`
  (a `swarm-routing/.github` checkout next to the repository) waits for the
  review and goes on with a warning 30 minutes after the PR opened
  (swarm-routing/.github#238).
- Never add a `Signed-off-by` trailer, for the maintainer or anyone else: a
  DCO sign-off is a person's own certification (CONTRIBUTING "Outside
  contributions").
- Releases are cut on request only: dispatch the release `bump` when the
  maintainer asks, once the version's `release:vX.Y.Z` issues are done and
  its exit criteria in the ladder (`docs/roadmap.md`, or the org ROADMAP's
  release train until it lands) are met; never approve a gated publish. A
  failed publish is recovered with "Re-run all jobs", never "Re-run failed
  jobs" (CONTRIBUTING "Cutting a release"). Never type a release's DOI: read
  it from Zenodo.
- Cite a paper in a public issue, PR or doc by its `https://doi.org/<DOI>`
  link, read from its record (`lit-search` confirms it), or, for a work with
  no DOI, by its publisher's or institution's page; never point into or name
  the private paper library there.

## Where to look

One line per task. Each row has a full entry in [`docs/where-to-look.md`](docs/where-to-look.md)
(the commands, the configuration, the issues behind it): read it before
changing what the row names.

| You want to… | Go to |
|--------------|-------|
| Change the CI every protocol repo runs | `.github/workflows/reusable-ns3-ci.yml` |
| Build a protocol's release or campaign image | `.github/workflows/reusable-ns3-image.yml` |
| Run one benchmark cell of any protocol repository | `.github/workflows/reusable-benchmark-cell.yml` |
| Cut a release of any org repository, or change how releases are made | `.github/workflows/reusable-release.yml` |
| Turn on SonarQube Cloud or Codecov for a C++ repo | `reusable-ns3-ci.yml` input `sonar`, `reusable-codecov.yml`, `templates/quality/` |
| Change the Python lint/coverage or the PR-title rule | `reusable-python-ci.yml` + `ruff.toml`; `reusable-pr-title.yml` |
| Change the licence rules or their gate | `tools/checks/check-headers.py`, `reusable-licence-check.yml`, CONTRIBUTING rule 1 |
| Change how outside contributions are accepted (DCO, contributor copyright lines) | CONTRIBUTING "Outside contributions", `tools/checks/check-dco.py`, `reusable-dco.yml` |
| Add or rename a label | `labels.json` + `CONTRIBUTING.md` + `ISSUE_TEMPLATE/` |
| List an org skill in every repo's AGENTS.md | `templates/agents/skills.md` |
| Change what every repo shares (org sections, badges, SECURITY, ADR template, Makefile) | `templates/` + `tools/org-sync/org_sync.py`; a template change turns every adopting repo's `org-sync` check red until its refresh PR lands |
| Bring a repo onto the templates | `tools/org-sync/org_sync.py init` (new repo) or `plan` → `apply` → `check` |
| Change the org security policy | `SECURITY.md`, `templates/SECURITY.md.in`; write no claim a repo cannot back |
| Change the C++ style | `.clang-format` |
| Change the org landing page | `profile/README.md` |
| Give a workflow the bot's token, or check the org App's permissions | `.github/actions/bot-token`; CONTRIBUTING "The bot's GitHub App" |
| Keep epic lists and org-managed files current without hand PRs | `tools/org-bot/org_bot.py`, `org-bot.yml` |
| Check that every release is on Zenodo, or archive a missed one | `tools/zenodo/zenodo.py`, `zenodo.yml` |
| Hold a repo's README, AI files and docs/ to the org standard | `tools/docs-review/check_docs.py`, `ai_files_review.py`, `ai-files-review.yml` |
| Check a diff against the org golden rules before review | `tools/protocol-review/check_invariants.py` |
| See open PRs' CI and review threads, wait for CI, or merge PRs that fall behind | `tools/pr-status/pr_status.py` |
| Confirm a reference, or find newer, citing, cited or related papers | `tools/lit-search/lit_search.py` |
| Change a repository's settings, rulesets, required checks, merge queue or Actions policy | its `.github/org-sync.toml` `[settings]`, `templates/rulesets/`, `tools/repo-settings/repo_settings.py` |
| Write or check a protocol's paper-fidelity sheet | `tools/fidelity/fidelity.py` |
| List, or refresh, the epics (README sections, ROADMAP, profile) | `tools/epics/epics.py`, `epics.yml` |
| Know where the org is going beyond ns-3, and which decisions wait on the maintainer | `ROADMAP.md` "Direction beyond ns-3"; epics #250, #251, #252, #272 |
| Make the agent files shorter, or the org's state readable by a new session | #277, #278, #281 under epic #141 |
| The org's invariants, labels, issue shape | [`swarm-routing/.github` CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md) |
| The reference implementation and its history | [`swarm-routing/AntHocNet`](https://github.com/swarm-routing/AntHocNet) (`AGENTS.md`, `CONTEXT.md`, `docs/adr/`) |
| Pick up open work | this repo's issues — highest open `priority:P*` first; newest open `handoff` issue for work in flight |
