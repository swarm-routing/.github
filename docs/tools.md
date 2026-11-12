# Tools, workflows and their checks

The reference for `swarm-routing/.github`: every file and directory it holds,
every self-test and read-only run, and how a change to a reusable workflow is
proven. [`AGENTS.md`](../AGENTS.md) keeps the short version and says when to
read this page: before adding, changing or running a tool or a workflow here.

## Layout

```
profile/README.md          org landing page
ROADMAP.md                 the org's phases, exit criteria and non-goals (epics carry the work)
CONTRIBUTING.md            org invariants + issue/label conventions (default for every repo)
ISSUE_TEMPLATE/            default issue forms (AntHocNet's set + literature)
pull_request_template.md   default PR template
labels.json                the label taxonomy (source of truth)
.clang-format              LLVM-based C++20 style
ruff.toml                  the Python lint baseline (explicit rules), used where a repo has none
tools/checks/check-headers.py   the licence-header gate (AntHocNet's rules, per-repo roots as flags; contributor copyright lines beneath the org line)
tools/checks/check-dco.py       the DCO gate of reusable-dco.yml: every PR commit's Signed-off-by matches its author email (members, the org App, Dependabot and agent commits on a member's PR exempt, #212)
tools/checks/check-swarm-core-pin.py   a protocol's swarm-core pin: one commit everywhere, and swarm-core main's core/ (reusable-swarm-core-pin.yml)
DCO                             the Developer Certificate of Origin 1.1, verbatim (CONTRIBUTING "Outside contributions")
tools/org-sync/org_sync.py      applies templates/ to a repo and checks drift (`check --changed-only BASE`: only a PR's own drift fails, the base's warns); `seeds` / `reseed FILE` for the repo-owned seeds; CITATION.cff `references:` and the README's citing list from `docs/references.bib` once it has an entry, else `[[references]]` (#308) (+ test_org_sync.py)
tools/epics/epics.py            the epic lists: each README's ## Epics, ROADMAP.md#epics, the profile's open epics (generated from issues)
tools/org-bot/org_bot.py        opens the refresh PRs across the org: epic lists (epics.py), templates (org_sync.py apply) and a new Zenodo concept's DOI (zenodo.py record)
tools/zenodo/zenodo.py          every release on Zenodo: checks each repo's releases against its concept record, archives the missed ones; `orphans`: released repos with no concept; `create`: a first concept from a tag (a failed first release, #226); `publish-release`: the release job's push of a release's own assets (opt-in `zenodo: true` of reusable-release.yml, #232); `record`: a repo's CITATION.cff doi, `zenodo_concept` and README DOI badge against its concept on Zenodo (`--write`: org-bot's `zenodo` task); `bibtex`: a repo's concept record as a BibTeX `@software` entry for `docs/references.bib`, every field read from Zenodo, the concept DOI and no url or version (#308)
tools/docs-review/check_docs.py   a repo's README, AI files and docs/ against the org standard (AntHocNet's): badges, explanation, site page, ns-3 image, layout, sections, links, citing (a released repo: DOI badge, CITATION.cff doi, citing section, references); the AI files' facts (paths, planned paths, open issues with --online, org-rule contradictions, required checks)
tools/docs-review/ai_files_review.py   the weekly AI-files review: check_docs.py's AI-files pass on every public repo, one `[docs] AI files: N finding(s)` issue per repo, opened, updated in place, closed when clean
tools/fidelity/fidelity.py      a protocol's docs/fidelity.md: the org shape (skeleton), valid sources and the list of unknowns (check), each locator and table value against the paper's text (verify), the review row (row); a repository's docs/references.bib (#308): its rules, the sheet's keys, doi.org links, the private-library text (bib check [--online]), Crossref's record as an entry (bib entry DOI --key K --role R), the Sources table between its markers (bib sources)
tools/fidelity/bib.py           the BibTeX reader and deterministic writer for docs/references.bib (stdlib; the API other tools import is in its docstring)
tools/protocol-review/check_invariants.py   the mechanical org golden rules (1-5, 8, 9) on a repo's diff, a line per rule the diff touches, exit 1 on a FAIL; rules 6 and 7 stay the reviewer's, with HINT lines at the likely spots
tools/pr-status/pr_status.py    open PRs across repos: `list`, `threads`, `wait` and `gate` (the review gate's wait, #294) (read-only) print a line per PR (head, CI verdict and counts, required checks missing on the head, workflows that ended in `startup_failure`, mergeable state) and per unresolved review thread (severity · title · path:line · id); a missing required check is never a pass; `merge` writes: it waits for green and squash-merges (a behind PR as it is, updated only where the rules require an up-to-date branch or with `--update`; a behind `bot/release` stops), one PR at a time per repo; every read backs off below `--min-rate` remaining API requests (#226)
tools/release/fixture/         the release self-test's caller: the minimal Commitizen config (.cz.toml), a `make dist`, and a CITATION.cff (the Zenodo push test)
tools/lit-search/lit_search.py  references and new papers from free sources only: confirm a DOI (Crossref vs Semantic Scholar and OpenAlex) or a title, the works citing or cited by a paper (OpenCitations + Semantic Scholar), search, related
tools/repo-settings/repo_settings.py   each repo's description, homepage, topics, merge settings and features, `main` and `release-tags` rulesets, security features, Actions policy (incl. fork-PR approval) and `release` environment as code: `plan`/`check` (read-only diff), `apply` (only the differences)
templates/rulesets/             the ruleset profiles repo_settings.py applies (protocol, tooling, data, site, merge-only): merge settings + the ruleset in the API shape; defaults.json: the parts every profile shares (features, security, Actions policy and its allowed actions, the tag ruleset, the release environment)
templates/                      what org-sync renders: AGENTS.md org sections (incl. Agent skills, agent defaults), CLAUDE.md, README badges,
                                SECURITY.md, LICENSE(-MIT), LICENSING.md, ADR template, Makefile per kind,
                                CITATION.cff and the README's Releases & citing section (`citation = true`; references from docs/references.bib, else `[[references]]`),
                                references.bib.in: the docs/references.bib seed (a header, no entry; #308),
                                the org-sync, dco and Scorecard workflows, the marketplace keys of .claude/settings.json,
                                the CodeRabbit settings (.coderabbit.yaml head/tail sections, #37),
                                codeowners/: .github/CODEOWNERS, a seed with the org's invariant paths per kind as its last section (#31),
                                quality/: the .codecov.yml and sonar-project.properties seeds of C++ repos
SECURITY.md                     the org default security policy (repos without their own get it)
CODE_OF_CONDUCT.md              the org default code of conduct: Contributor Covenant 2.1, reports to the maintainer's GitHub profile (no email)
SUPPORT.md                      the org default support policy: issues for bugs, features and questions, no private support
.github/FUNDING.yml             the org default Sponsor button (GitHub Sponsors: danieljoppi)
.github/actions/bot-token/      the bots' token: the org GitHub App's installation token, else ORG_BOT_TOKEN (#21; CONTRIBUTING "The bot's GitHub App")
.github/workflows/         reusable-ns3-ci.yml, reusable-ns3-image.yml, reusable-release.yml, reusable-benchmark-cell.yml, reusable-python-ci.yml,
                           reusable-pr-title.yml, reusable-licence-check.yml, reusable-dco.yml, reusable-org-sync-check.yml, reusable-codecov.yml, reusable-scorecard.yml, reusable-swarm-core-pin.yml,
                           reusable-review-gate.yml (#294), review-gate.yml (this repository's own, from the PR's head),
                           sync-labels.yml, epics.yml, ai-files-review.yml, zenodo.yml, org-bot.yml, repo-settings.yml, scorecard.yml, ci.yml, ns3-image-selftest.yml, release-selftest.yml,
                           benchmark-cell-selftest.yml
LICENSE, LICENSE-MIT, LICENSING.md   the licence per path (LICENSING.md): the tooling MIT OR GPL-2.0-only, the docs GPL-2.0-only,
                                     CODE_OF_CONDUCT.md CC-BY-4.0, DCO verbatim copies only
```

## Self-tests and read-only runs

Run the self-test of every tool you changed, and the lint lines, before
pushing (`ci.yml` runs them all):

```bash
pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1   # once, as ci.yml
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
python3 -I tools/checks/check-headers.py --self-test && python3 -I tools/checks/check-headers.py --dual '' .
python3 -I tools/checks/check-dco.py --self-test   # the DCO gate: signed, unsigned, mismatched, exempt (member, write access, bots, merges, agent commits on a member's PR), a real git history
python3 -I tools/checks/check-swarm-core-pin.py --self-test   # against a local swarm-core and fixture repos
python3 -I tools/org-sync/test_org_sync.py   # org-sync against fixture repos (references: the seed, bib only, [[references]] only, both, a malformed bib)
python3 -I tools/epics/epics.py --self-test     # the epic lists, on fixture data
python3 -I tools/zenodo/zenodo.py --self-test   # the Zenodo check and archive, against a fake Zenodo (publish-release: first release, next version, idempotent re-run, refusal, retries; record: unrecorded, written, two concepts refused; bibtex: the entry, roles, unrecorded, unreleased and unarchived)
python3 -I tools/org-bot/org_bot.py --self-test # the refresh PRs, against local bare repos and a fake GitHub (the zenodo task: record, then apply's badge)
python3 -I tools/docs-review/check_docs.py --self-test   # the docs standard and the AI-files facts, a passing and a failing fixture repo per check; a settings-only repo skips the badge row and the org sections
python3 -I tools/docs-review/check_docs.py ../AntHocNet --online   # read-only, a real repo's docs and AI files (issue states through gh)
python3 -I tools/docs-review/ai_files_review.py --self-test   # the weekly review's issue sync, against local bare repos and a fake GitHub
python3 -I tools/docs-review/ai_files_review.py run --dry-run --repos .github,skills   # read-only, what the weekly run would open, update or close
python3 -I tools/fidelity/fidelity.py --self-test   # the fidelity-sheet checker, on fixture sheets; the bib reader and writer, every bib check finding, entry from a recorded Crossref record (retry, no record), sources rewrite and idempotence (no network)
python3 -I tools/fidelity/fidelity.py bib check ../ARA   # read-only, a real repository's references.bib and its private-library lines
python3 -I tools/fidelity/fidelity.py bib entry 10.1109/ICPPW.2002.1039715 --key G02 --role implemented   # read-only, Crossref's record as an entry
python3 -I tools/protocol-review/check_invariants.py --self-test   # a passing and a failing fixture repo per checked rule; a hinted and an unhinted one for 6 and 7
python3 -I tools/pr-status/pr_status.py --self-test   # the PR view, against a fake GitHub (CI states, a startup_failure run and missing required checks, threads, a CodeRabbit body reduced to its heading, wait), and merge against a simulated one (behind -> update -> merged where the rules require it, behind merged as it is where they do not, `--update`, an outdated PR reported `clean`, a refusal as not up to date, a behind `bot/release`, sequence, failing check, open thread, conflict, draft, refused, unreported required check, startup failure, already merged; wait at the timeout: a missing required check fails only with nothing else pending; wait --merged: merged, closed, a thread, a red required check (a red report-only one ignored), auto-merge off, the timeout, a missing PR, one PR stopped while another is pending (1 at once), --json for merged, stopped and timeout; CodeRabbit's review awaited before the threads are read, a warning at --review-timeout, its own check run no CI failure; wait --review; gate: reviewed, waiting until the review lands, declined with CodeRabbit's reason, a decline or a CodeRabbit check run from before ready_for_review ignored, another author's words ignored, draft, time-out, a failed read retried, reads failing until the time-out, a missing PR)
python3 -I tools/lit-search/lit_search.py --self-test   # confirm, citing, refs, search, related on recorded responses of each source, a source down or rate-limited, keys never leaked
python3 -I tools/repo-settings/repo_settings.py --self-test   # plan, check, apply against a fake GitHub (each field's drift, ruleset create/update, unmanaged ruleset left alone, private masked, 403 refused, dry run; merge_queue rule, its table overrides and validation, refused without a merge_group trigger behind each required check; security on in order, own CodeQL kept, private unsupported, Actions policy and an uncovered action refused, fork-PR approval for all outside contributors (a note on a private repository), 409 org policy, release environment, idempotent)
python3 -I tools/org-bot/org_bot.py run --dry-run --repos .github,Termite   # read-only, what it would propose
python3 -I tools/zenodo/zenodo.py sync --repo swarm-routing/AntHocNet --dry-run   # read-only, the real records
python3 -I tools/zenodo/zenodo.py orphans --repos benchmarks,ARA   # read-only, released repos without a concept
python3 -I tools/zenodo/zenodo.py create --repo swarm-routing/benchmarks --tag v0.1.0   # read-only without --publish and ZENODO_TOKEN: what it would create
python3 -I tools/zenodo/zenodo.py bibtex swarm-routing/ns3-tools --key ns3tools --role tool   # read-only, no token: the concept record as @software
python3 -I tools/pr-status/pr_status.py list --repos .github,skills   # read-only, the open PRs and their unresolved threads
python3 -I tools/pr-status/pr_status.py merge --dry-run .github#N   # read-only, what merge would do now (would update / would merge / would wait)
python3 -I tools/lit-search/lit_search.py confirm 10.1613/jair.530   # read-only, free: Crossref, Semantic Scholar, OpenAlex agree
python3 -I tools/repo-settings/repo_settings.py plan .github skills   # read-only, live settings vs each repo's [settings]
pip install ruff==0.17.1 && ruff check tools && ruff format --check tools   # as reusable-python-ci.yml
clang-format-18 --style=file:.clang-format --dump-config >/dev/null
```

## Validating a change to a reusable workflow


A change to `reusable-ns3-ci.yml` is validated by running its step scripts in
an `ns3-dev` image against `swarm-routing/ns3-containers`' `test/fixtures/`
module (see that repo's AGENTS.md), then by a caller repo's PR. A change to
`reusable-benchmark-cell.yml` runs `benchmark-cell-selftest.yml` on its PR (one
build-mode cell); its prebuilt mode is proven by a protocol repo's caller. A change to
`reusable-ns3-image.yml` runs `ns3-image-selftest.yml` on its PR (build and
test only); its push, sign and attest steps are proven by a `push: true`
caller after merge. A change to `reusable-release.yml` runs `release-selftest.yml`
on its PR: a dry run on `tools/release/fixture/` (bump to v0.1.0, `make dist`,
checksums, SBOM, real attestations and their verification, nothing pushed),
then a check of every file it would have published, then `zenodo.py
publish-release` on those files against the fake Zenodo (`fake-zenodo`; also
on a change to `tools/zenodo/`); its bump PR (`propose`) and its
tag-and-publish job are proven by the first caller's release (ns3-tools#26),
its opt-in `zenodo` job by a `zenodo-sandbox: true` run and the first
caller's release with `zenodo: true` (#232).
