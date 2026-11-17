# Developer guide

This repository holds what every swarm-routing repository shares: the
reusable GitHub Actions workflows other repositories call, the templates
`org-sync` renders into them, the issue forms and labels, the org's
documents (CONTRIBUTING, ROADMAP, the profile page), and the Python and
shell tools under `tools/` (each with a `--self-test`). Nothing here is
compiled; a change is tested by the tools' self-tests and, for a reusable
workflow, by a caller. This page shows how to set up, test, lint and try a
change, and what CI checks. Every file and every self-test is listed in
[tools.md](tools.md), and [where-to-look.md](where-to-look.md) maps tasks to
files; the rules a change must keep are in [AGENTS.md](../AGENTS.md)
("Golden rules", notably rule 10: reusable workflows are a public
contract); how issues and pull requests work is
[CONTRIBUTING.md](../CONTRIBUTING.md).

## Prerequisites

| Tool | Version | Needed for |
| --- | --- | --- |
| Linux or macOS, `git`, `bash` | any recent | everything |
| Python | 3.11 or newer (`tomllib`) | every tool (standard library only) |
| PyYAML | any recent | parsing the issue forms (the "Forms, labels, style parse" check) |
| ruff | 0.17.1 | Python lint and format |
| Go | go.mod's `toolchain` version (1.27.4) | the Go tools (`cmd/`, `internal/`) and the go-ci fixtures |
| Docker | any recent | only to build the `ci-tools` image locally |
| actionlint, shellcheck | `pip install actionlint-py==1.7.12.25 shellcheck-py==0.10.0.1` | workflow lint (actionlint also shellchecks `run:` blocks) |
| GitHub CLI `gh`, logged in | any recent | only the read-only runs against the real org, and `epics.py` |

## Get the code

```bash
git clone https://github.com/swarm-routing/.github.git
cd .github
```

There are no submodules. Several tools act on another repository's
checkout (`org_sync.py plan ../ARA`, `check_docs.py ../AntHocNet`), so the
usual layout is this repository next to the others, as `../.github` from
each of them.

## Dependencies

None to install for the tools: they use the Python standard library. The
reusable workflows pin every action by commit SHA (the allowlist is
`templates/rulesets/defaults.json` `selected_actions`). How the org's
repositories depend on each other (release locks, the swarm-core pin) is
CONTRIBUTING "Dependencies"; the vcpkg rollout that will replace the locks
is #489.

## Build

Only the Go tools compile: `CGO_ENABLED=0 go build -trimpath ./...` at the
root (the `ci-tools` image builds every `cmd/<tool>` the same way). Everything
else takes effect from `main`: GitHub reads the community
defaults and every `@main` workflow reference from the default branch, and
`org-sync` renders `templates/` into each repository through org-bot's
refresh PRs after a template change merges.

## Test

Every tool has a `--self-test` against fixtures or a fake GitHub; CI runs
them all. The same locally:

```bash
grep -oE "tools/[^ ]+\.py --self-test" .github/workflows/ci.yml | sort -u |
  while read -r tool flag; do python3 -I "$tool" "$flag" </dev/null >/dev/null || echo "FAIL $tool"; done
python3 -I tools/org-sync/test_org_sync.py      # org-sync's own test file
bash tools/downstream/downstream.sh --self-test
python3 -I tools/org-sync/org_sync.py profile . --check   # the profile's badge table is today's render
python3 -c "import yaml,glob; [yaml.safe_load(open(f)) for f in glob.glob('ISSUE_TEMPLATE/*.yml')]"
python3 -m json.tool labels.json >/dev/null
go test -race ./...                             # the Go tools (cmd/, internal/)
```

Run the self-test of the tool you changed at least; [tools.md](tools.md)
("Self-tests and read-only runs") says what each covers and gives a
read-only run against the real org for most of them.

A change to a reusable workflow is proven in two steps: its self-test
workflow (`ns3-image-selftest.yml`, `benchmark-cell-selftest.yml`,
`release-selftest.yml`) and then a real caller pointed at your branch
([tools.md](tools.md) "Validating a change to a reusable workflow").

## Run

The tools run against any org repository checked out next to this one, and
most only read:

```bash
python3 -I tools/org-sync/org_sync.py plan ../ARA        # what org-sync would change there
python3 -I tools/docs-review/check_docs.py ../ARA        # the docs standard, PASS/WARN/FAIL per check
python3 -I tools/protocol-review/check_invariants.py --help
python3 -I tools/pr-status/pr_status.py --help           # open PRs' CI and review threads (needs gh)
```

Each tool's docstring (the top of the file) is its manual.

## Docker and dev containers

Only the `ci-tools` image is built here: `docker build -f
docker/ci-tools/Dockerfile -t ci-tools .` from the root, then
`docker run --rm ci-tools list`. The images the reusable workflows use
(`ghcr.io/swarm-routing/ns3-dev`) are built in swarm-routing/ns3-containers.
There is no `.devcontainer/`.

## Lint and format

```bash
actionlint .github/workflows/*.yml            # also shellchecks run: blocks
ruff check tools && ruff format --check tools # as reusable-python-ci.yml, with this repository's ruff.toml
ruff format tools                             # fix formatting
python3 -I tools/checks/check-headers.py --dual '' .   # licence headers (everything here is dual-licensed tooling)
```

## CI map

| Workflow | Job (check name) | What it checks | Required |
| --- | --- | --- | --- |
| `ci.yml` | `lint` | licence headers, every tool's self-test, the profile table, the forms, labels and style files parse, actionlint | yes |
| `ci.yml` | `python / python` | ruff and the Python tests with coverage | yes |
| `ci.yml` | `title / title` | the PR title is a lowercase Conventional Commit | yes |
| `review-gate.yml` | `review / coderabbit` | CodeRabbit has reviewed the PR | yes |
| `ns3-image-selftest.yml`, `benchmark-cell-selftest.yml`, `release-selftest.yml` | | the reusable image, benchmark-cell and release workflows on fixtures | no |
| `go-ci-selftest.yml` | | `reusable-go-ci.yml` on a passing and a failing fixture module | no |
| `ci-tools-image.yml` | | the Go tools and the `ci-tools` image: build once, test by digest, promote on `main` | no |
| `org-bot.yml`, `epics.yml`, `zenodo.yml`, `repo-settings.yml`, `ai-files-review.yml`, `sonar-triage.yml`, `bestpractices.yml`, `repo-metadata.yml`, `sync-labels.yml`, `labels.yml`, `scorecard.yml` | | scheduled or dispatched automation across the org (CONTRIBUTING "Automation") | no |

The required checks are the ones the `main` ruleset lists: `gh api
repos/swarm-routing/.github/rules/branches/main`. `main` merges through a
merge queue, so a pull request is merged by enabling auto-merge.

## Release

This repository is not released: callers use `@main`, so a reusable
workflow never renames or removes an input or changes a default's meaning,
and a breaking change needs a new file and an issue in every caller (golden
rule 10). The procedure every other repository follows is
[CONTRIBUTING "Cutting a release"](../CONTRIBUTING.md#cutting-a-release),
run by `reusable-release.yml` from here.

## Troubleshooting

- **After a template change merges, every repository's `check / org-sync`
  warns.** Expected: org-bot opens a `bot/org-sync` refresh PR in each. A PR
  that edits a managed section by hand stays red; change the template here.
- **A tool works locally but not in CI.** CI runs it with `python3 -I`, which
  ignores your environment and the current directory's modules; run it the
  same way.
- **`actionlint` reports a shellcheck finding.** It is in a `run:` block;
  fix the script, not the lint.
- **A new third-party action is refused by `repo-settings`.** It must be in
  `templates/rulesets/defaults.json` `selected_actions`, in the same PR or
  merged first.
- **A loop over the self-tests stops early or a test misbehaves.** Give
  each test `</dev/null`, as above: a test that reads standard input would
  otherwise consume the loop's own input.
- **A self-test that talks to GitHub fails offline.** Self-tests use fixtures
  or a fake GitHub; only the read-only runs need the network and `gh`.
