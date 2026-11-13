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
tools/checks/check-dco.py       the DCO gate of reusable-dco.yml: every PR commit's Signed-off-by matches its author email (members, bot commits on a bot's or member's PR, and agent commits on a member's PR exempt, #212, #368)
tools/checks/check-swarm-core-pin.py   a protocol's swarm-core pin: one commit everywhere, and swarm-core main's core/ (reusable-swarm-core-pin.yml)
DCO                             the Developer Certificate of Origin 1.1, verbatim (CONTRIBUTING "Outside contributions")
tools/org-sync/org_sync.py      applies templates/ to a repo and checks drift (`check --changed-only BASE`: only a PR's own drift fails, the base's warns); `seeds` / `reseed FILE` for the repo-owned seeds; CITATION.cff `references:` and the README's citing list from `docs/references.bib` once it has an entry, else `[[references]]` (#308; a proceedings `@incollection` is a `conference-paper`, #331); `citation-refs [REPO] [--check]`: only CITATION.cff's `references:` block from the bib, any repository with both files; `coderabbit_path_filters`: a repository's own CodeRabbit path filters, rendered after the org's in the managed head (swarm-routing/AntHocNet#838); `bestpractices_project`: a repository's bestpractices.dev project id, which turns on the OpenSSF Best Practices badge (#23), with `"bestpractices"` in `badges` when a repository sets its own list (+ test_org_sync.py)
tools/epics/epics.py            the epic lists: each README's ## Epics, ROADMAP.md#epics, the profile's open epics (generated from issues)
tools/org-bot/org_bot.py        opens the refresh PRs across the org: epic lists (epics.py), templates (org_sync.py apply) and a new Zenodo concept's DOI (zenodo.py record)
tools/zenodo/zenodo.py          every release on Zenodo: checks each repo's releases against its concept record, archives the missed ones; `orphans`: released repos with no concept; `create`: a first concept from a tag (a failed first release, #226); `publish-release`: the release job's push of a release's own assets (opt-in `zenodo: true` of reusable-release.yml, #232); `record`: a repo's CITATION.cff doi, `zenodo_concept` and README DOI badge against its concept on Zenodo (`--write`: org-bot's `zenodo` task); `bibtex`: a repo's concept record as a BibTeX `@software` entry for `docs/references.bib`, every field read from Zenodo, the concept DOI and no url or version (#308)
tools/bestpractices/bestpractices.py   OpenSSF Best Practices (bestpractices.dev, read-only: the site has no write API): `answers DIR [--write]`: the passing answers a repository shows, as `.bestpractices.json` (owner-only criteria `?`, crypto N/A unless `bestpractices_crypto = true`); `register OWNER/NAME [--answers FILE]`: the project id, its org-sync line and the proposal links (`/en/projects/<id>/passing/edit?…`, under 6000 characters each, owner-only left out) if the site has it, else where to register (the site has no pre-filled registration form); `check [--repos NAME[=ID]] [--issues]`: each registered project against its repository (#391)
tools/docs-review/check_docs.py   a repo's README, AI files and docs/ against the org standard (AntHocNet's): badges, explanation, site page, ns-3 image, layout, sections, links, citing (a released repo: DOI badge, CITATION.cff doi, citing section, references); the AI files' facts (paths, planned paths, open issues with --online, org-rule contradictions, required checks)
tools/docs-review/ai_files_review.py   the weekly AI-files review: check_docs.py's AI-files pass on every public repo, one `[docs] AI files: N finding(s)` issue per repo, opened, updated in place, closed when clean
tools/fidelity/fidelity.py      a protocol's docs/fidelity.md: the org shape (skeleton), valid sources and the list of unknowns (check), each locator and table value against the paper's text (verify), the review row (row); a repository's docs/references.bib (#308): its rules, the sheet's keys, doi.org links, the private-library text (bib check [--online]), Crossref's record as an entry, else DataCite's (bib entry DOI --key K --role R), a work with no DOI from its repository's record: citation_* tags, the handle's OAI-PMH ETD-MS or Dublin Core record (bib entry --url URL, #342), the Sources table between its markers (bib sources), read-only: the DOIs and [KEY]s cited outside the bib, each in it or not, and the bib's entries as key, role, link (bib scan, #338); `notdoi = {DOI}` on an entry silences `--online`'s title match for that DOI
tools/fidelity/bib.py           the BibTeX reader and deterministic writer for docs/references.bib (stdlib; the API other tools import is in its docstring)
tools/protocol-review/check_invariants.py   the mechanical org golden rules (1-5, 8, 9) on a repo's diff, a line per rule the diff touches, exit 1 on a FAIL; rules 6 and 7 stay the reviewer's, with HINT lines at the likely spots
tools/pr-status/pr_status.py    open PRs across repos: `list`, `threads`, `wait` and `gate` (the review gate's wait, #294) (read-only) print a line per PR (head, CI verdict and counts, required checks missing on the head, workflows that ended in `startup_failure`, mergeable state) and per unresolved review thread (severity · title · path:line · id); a missing required check is never a pass; `merge` writes: it waits for green and squash-merges (a behind PR as it is, updated only where the rules require an up-to-date branch or with `--update`; a behind `bot/release` stops), one PR at a time per repo; `queued` (read-only): merged, in the merge queue (a `gh-readonly-queue/<base>/pr-N-*` `merge_group` run since its head was pushed, with each workflow's status) or neither (a failed queue run means GitHub took it out; REST's auto-merge, which is none for a queued PR too; a removal by hand with no push and no failed run still reads queued), the `pr-shepherd` skill's check after enabling auto-merge in a merge-queue repository; every read backs off below `--min-rate` remaining API requests (#226)
tools/images/rolling_tags.py    a release image's rolling tags: `move` copies its digest to `latest-<profile>` (and `latest`, for optimized), only for a release version, never back to an older release, failing closed on a registry error; `reusable-ns3-image.yml` runs it after the signature verifies, and without `--digest` (with `--verify-signature`) it repairs a release whose step failed, from the version tag's digest (#373)
tools/images/retention.py       the 2-day retention of `<repo>-dev` packages (#371, epic #370): `pinned` lists every `sha256:<hex>` and `ghcr.io/<org>/<pkg>:<tag>` in the tracked text files of every public, unarchived, non-fork repository's default branch and every open benchmarks PR head (counts per package; `--out` the JSON); `sweep` deletes a `-dev` package's tagged versions older than `--days` that nothing pins, never the newest image, an untagged version, a kept image's signatures, a non-`-dev` package or `ns3-dev`; dry run unless `--apply`; fails closed when a repository cannot be read; `reusable-dev-image-cleanup.yml` runs it
tools/release/fixture/         the release self-test's caller: the minimal Commitizen config (.cz.toml), a `make dist`, and a CITATION.cff (the Zenodo push test)
tools/lit-search/lit_search.py  references and new papers from free sources only: confirm a DOI (Crossref vs Semantic Scholar and OpenAlex) or a title, the works citing or cited by a paper (OpenCitations + Semantic Scholar), search, related
tools/repo-settings/repo_settings.py   each repo's description, homepage, topics, merge settings and features, `main` and `release-tags` rulesets, security features, Actions policy (incl. fork-PR approval) and `release` environment as code: `plan`/`check` (read-only diff), `apply` (only the differences)
templates/rulesets/             the ruleset profiles repo_settings.py applies (protocol, tooling, data, site, merge-only): merge settings + the ruleset in the API shape; defaults.json: the parts every profile shares (features, security, Actions policy and its allowed actions, the tag ruleset, the release environment)
templates/                      what org-sync renders: AGENTS.md org sections (incl. Agent skills, agent defaults), CLAUDE.md, README badges,
                                SECURITY.md, LICENSE(-MIT), LICENSING.md, ADR template, Makefile per kind,
                                CITATION.cff and the README's Releases & citing section (`citation = true`; references from docs/references.bib, else `[[references]]`),
                                references.bib.in: the docs/references.bib seed (the header, no entry; #308), references-header.bib: that header, a managed `bib-header` section between `% org-sync:begin/end` lines (#343),
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
                           reusable-dev-image-cleanup.yml (#371),
                           reusable-review-gate.yml (#294), review-gate.yml (this repository's own, from the PR's head),
                           sync-labels.yml, epics.yml, ai-files-review.yml, zenodo.yml, bestpractices.yml, org-bot.yml, repo-settings.yml, scorecard.yml, ci.yml, ns3-image-selftest.yml, release-selftest.yml,
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
python3 -I tools/checks/check-swarm-core-pin.py --self-test   # against a local swarm-core and fixture repos; --bump rewrites a stale pin everywhere (extra files included), leaves a current one, refuses a split one
python3 -I tools/org-sync/test_org_sync.py   # org-sync against fixture repos (references: the seed, the managed bib header (a hand edit and a changed template are drift, apply keeps the entries and the repository's own lines, an old unmarked header adopted and replaced, #343), bib only, [[references]] only, both, a malformed bib; citation-refs: drift, the rest of the file byte-identical, idempotent, appended, removed, the seed left alone; LNCS and proceedings @incollection as conference-paper)
python3 -I tools/org-sync/org_sync.py citation-refs ../AntHocNet --check   # read-only: is CITATION.cff's references: block the bib's render
python3 -I tools/epics/epics.py --self-test     # the epic lists, on fixture data
python3 -I tools/zenodo/zenodo.py --self-test   # the Zenodo check and archive, against a fake Zenodo (publish-release: first release, next version, idempotent re-run, refusal, retries; record: unrecorded, written, two concepts refused; bibtex: the entry, roles, the key from ORG_KEYS (= CONTRIBUTING's table), unrecorded, unreleased and unarchived)
python3 -I tools/bestpractices/bestpractices.py --self-test   # answers on fixture repositories (C++ with CI, CodeQL, sanitizers, fuzzing; Python scripts only; outside the org; crypto by include and by override; owner-only always ?), stdlib crypto (`hmac`), compiled code without a build file, a `.clang-tidy` no workflow runs, `python -O`; register (looked up first; not registered: where to register, nothing proposed; registered: the proposal links from `fixtures/anthocnet-answers.json`, AntHocNet's reviewed answers, each under 6000 characters, every pair intact and in one link, owner-only left out), check against a fake site and GitHub (a disagreeing answer, a removed file, a lost level, a registered repo without the key, an unreadable project, a failed lookup, a non-object JSON and a failed issue write each isolated to their repository, issues read on every page, opened, unchanged, updated, closed, dry run) (no network)
python3 -I tools/org-bot/org_bot.py --self-test # the refresh PRs, against local bare repos and a fake GitHub (the zenodo task: record, then apply's badge; the swarm-core-pin task: a stale pin gets one PR on org-bot/swarm-core-pin, a current one none, a second swarm-core move updates that PR, the same target is left alone, a hand-opened bump to the same commit gets no duplicate)
python3 -I tools/docs-review/check_docs.py --self-test   # the docs standard and the AI-files facts, a passing and a failing fixture repo per check; a settings-only repo skips the badge row and the org sections; AGENTS.md over its size budget warns (own text, org-sync sections, a settings-only whole file)
python3 -I tools/docs-review/check_docs.py ../AntHocNet --online   # read-only, a real repo's docs and AI files (issue states through gh)
python3 -I tools/docs-review/ai_files_review.py --self-test   # the weekly review's issue sync, against local bare repos and a fake GitHub
python3 -I tools/docs-review/ai_files_review.py run --dry-run --repos .github,skills   # read-only, what the weekly run would open, update or close
python3 -I tools/fidelity/fidelity.py --self-test   # the fidelity-sheet checker, on fixture sheets; the bib reader and writer, every bib check finding (each wording of the private-library rule and its near misses), entry from a recorded Crossref record (retry, no record) and from a recorded DataCite record after Crossref's 404 (type mapping, a Zenodo DOI never asked), sources rewrite and idempotence, notdoi (silences only its DOI; not a DOI is a finding), scan (in and not in the bib, the own DOI, badge and backticks, code and YAML comments only, evals and fixtures skipped, read-only, a bib that does not parse), entry --url from recorded MSpace and eCommons landing pages and OAI-PMH records (ETD-MS degree and grantor, the redirect's host, an OAI error moves to the next format, a record with no degree is @misc), citation_* tags alone, refusals (no tags or record, no title, a page naming a DOI, 404, unreachable) (no network)
python3 -I tools/fidelity/fidelity.py bib check ../ARA   # read-only, a real repository's references.bib and its private-library lines
python3 -I tools/fidelity/fidelity.py bib scan ../AntHocNet   # read-only, what a real repository cites outside its bib, and the bib
python3 -I tools/fidelity/fidelity.py bib entry 10.1109/ICPPW.2002.1039715 --key G02 --role implemented   # read-only, Crossref's record as an entry
python3 -I tools/fidelity/fidelity.py bib entry 10.17877/de290r-14312 --key PG460 --role compared   # read-only, no Crossref record: DataCite's
python3 -I tools/fidelity/fidelity.py bib entry --url https://hdl.handle.net/1993/20935 --key W07 --role implemented   # read-only, no DOI: MSpace's page and OAI-PMH record
python3 -I tools/protocol-review/check_invariants.py --self-test   # a passing and a failing fixture repo per checked rule; a hinted and an unhinted one for 6 and 7
python3 -I tools/pr-status/pr_status.py --self-test   # the PR view, against a fake GitHub (CI states, a startup_failure run and missing required checks, threads, a CodeRabbit body reduced to its heading, wait), and merge against a simulated one (behind -> update -> merged where the rules require it, behind merged as it is where they do not, `--update`, an outdated PR reported `clean`, a refusal as not up to date, a behind `bot/release`, sequence, failing check, open thread, conflict, draft, refused, unreported required check, startup failure, already merged; wait at the timeout: a missing required check fails only with nothing else pending; wait --merged: merged, closed, a thread, a red required check (a red report-only one ignored), auto-merge off, a queued PR (auto_merge null) still waited for, with a group branch or waiting behind full groups (the timeline's last queue event), removed since stops, a merge that lands between the reads, the timeout, a missing PR, one PR stopped while another is pending (1 at once), --json for merged, stopped and timeout; CodeRabbit's review awaited before the threads are read, a warning at --review-timeout, its own check run no CI failure; wait --review; queued: merged, queued for the current head, a queue run older than the head, a failed queue run, a `pr-80` branch never read as `pr-8`'s, auto-merge as REST reports it; gate: reviewed, waiting until the review lands, declined with CodeRabbit's reason, a decline or a CodeRabbit check run from before ready_for_review ignored, another author's words ignored, draft, time-out, a failed read retried, reads failing until the time-out, a missing PR)
python3 -I tools/images/rolling_tags.py --self-test   # the rolling tags, against a fake registry: first release per profile, newer, same, older (never back), v1.10 vs v1.9, no `v`, a campaign tag, a pre-release and `latest` (nothing moved), a failing registry (fails closed), a transient error (retried), no version label, a copy with another digest, the repair (version tag's digest, signature checked, version tag never written), an unsigned digest and a missing version tag (refused)
python3 -I tools/images/retention.py --self-test   # the -dev retention, against a fake GitHub and local git remotes: pins from a manifest, a ##PROV## line, a tag at a sentence's end and an open benchmarks PR head (a binary file, archived, fork and private repositories not read); kept: a pinned digest (and its signature), a pinned tag, a younger image (and its attestation), an untagged version, the newest image; deleted: an unpinned image older than 2 days, then its .sig and referrers versions, an orphan signature; a non-`-dev` package and `ns3-dev` refused; dry run deletes nothing; a failed delete (exit 1, its signatures untried), GHCR's last-version refusal, a version already gone; fail closed: an API that keeps failing, a repository that cannot be cloned, benchmarks missing, a PR head that cannot be fetched
python3 -I tools/images/retention.py pinned --org swarm-routing   # read-only, what committed files pin, counts per package
python3 -I tools/images/retention.py sweep --org swarm-routing --package anthocnet-dev   # read-only (no --apply), what the sweep would delete; reading the versions needs read:packages
python3 -I tools/lit-search/lit_search.py --self-test   # confirm (a chapter's book and series as one venue, a placeholder venue warned), citing, refs, search, related on recorded responses of each source, a source down or rate-limited, keys never leaked
python3 -I tools/repo-settings/repo_settings.py --self-test   # plan, check, apply against a fake GitHub (each field's drift, ruleset create/update, unmanaged ruleset left alone, private masked, 403 refused, dry run; merge_queue rule, its table overrides and validation, refused without a merge_group trigger behind each required check; security on in order, own CodeQL kept, private unsupported, Actions policy and an uncovered action refused, fork-PR approval for all outside contributors (a note on a private repository), 409 org policy, release environment, idempotent)
python3 -I tools/org-bot/org_bot.py run --dry-run --repos .github,Termite   # read-only, what it would propose
python3 -I tools/zenodo/zenodo.py sync --repo swarm-routing/AntHocNet --dry-run   # read-only, the real records
python3 -I tools/zenodo/zenodo.py orphans --repos benchmarks,ARA   # read-only, released repos without a concept
python3 -I tools/zenodo/zenodo.py create --repo swarm-routing/benchmarks --tag v0.1.0   # read-only without --publish and ZENODO_TOKEN: what it would create
python3 -I tools/zenodo/zenodo.py bibtex swarm-routing/ns3-tools --role tool   # read-only, no token: the concept record as @software
python3 -I tools/bestpractices/bestpractices.py register swarm-routing/AntHocNet --dir ../AntHocNet   # read-only: the project id and its proposal links, or where to register
python3 -I tools/bestpractices/bestpractices.py check --repos AntHocNet   # read-only without --issues: the entry against the repository
python3 -I tools/pr-status/pr_status.py list --repos .github,skills   # read-only, the open PRs and their unresolved threads
python3 -I tools/pr-status/pr_status.py merge --dry-run .github#N   # read-only, what merge would do now (would update / would merge / would wait)
python3 -I tools/pr-status/pr_status.py queued .github#N   # read-only, merged / queued (the queue runs' status) / not queued (REST's auto-merge)
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
