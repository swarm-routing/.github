# 0003. An RCAPA for every ns-3 bug and every regression in a published library

- **Status:** accepted
- **Date:** 2026-11-16
- **Issue:** #538
- **Amended:** 2026-11-16, the same day: "published" is a library consumed at a version; images only for their composition; repositories nothing consumes at a version are out (maintainer decisions, below)

## Context

Since 2026-11-16 every defect in upstream ns-3, and every investigation of
one, gets an **RCAPA** (root cause analysis with corrective and preventive
actions): a ticket first, then a document with five cited whys, a
reproducer, diagrams, the actions and a timeline. The register lives in
swarm-routing/sim-tools (`docs/ns3-bugs.md`, `docs/ns3-rcapa/`, IDs
`NS3-NNN`), and a defect in how we carry a report is a `PROC-NNN` there
(PROC-001, swarm-routing/sim-tools#247).

Our own defects had no such record. A bug in a protocol, a tool or a
pipeline was an ordinary `bug` issue, whatever it cost. That is enough for
most bugs, which are caught on `main` before anyone depends on them. It is
not enough for a **regression in a published release**: someone may have
installed it (a GitHub release, a Zenodo DOI, PyPI, the vcpkg port), cited
it, or published numbers from it, so the record has to say what was
affected, how it was found, why our checks let it out, and which release
carries the fix.

The maintainer accepted the recommendation to extend RCAPA to our own bugs
(2026-11-16), then narrowed it the same day: RCAPA covers our own defects
**only when they are regressions in a published package**. A bug or change
that never reached a release, such as a divergence caught on `main` before
the next release, needs no RCAPA; an ordinary `bug` issue is enough.

Later the same day the maintainer defined "published": a library another
project consumes at a specific version. Docker images get no RCAPA unless
the image's composition is the cause, and the repositories whose output no
project pins by version (the reusable workflows, the site, the plugin, the
datasets, the upstream bridge) get none for their own changes. This ADR is
written to that amended decision.

## Decision

### When an RCAPA is required

**Published** means a library another project consumes at a specific
version: a swarm-core release (the protocols' `swarm-core.lock`, the vcpkg
baseline), an ns3-tools release (AntHocNet's `ns3-tools.lock`, PyPI), a
protocol core's vcpkg port, a port recipe in swarm-routing/vcpkg-registry at
a baseline, and any other release a consumer pins by version (maintainer
decision 2026-11-16). A GitHub release or a Zenodo DOI alone does not make a
repository a library: what counts is a consumer pinning it.

| Defect | RCAPA |
|--------|-------|
| A bug in upstream ns-3, or an investigation of one | **always**: `NS3-NNN` in swarm-routing/sim-tools, unchanged |
| A defect in how we carry an ns-3 report upstream | **always**: `PROC-NNN` in swarm-routing/sim-tools, unchanged |
| A **regression in a published library**: it worked in a version a consumer pins and broke in a later one | **yes**: `<PREFIX>-NNN` in that library's repository |
| A bug in a Docker image (`ns3-dev`, `ci-tools`, any image) | **no** by default; **yes** only when traced to the image's composition (its Dockerfile, `build-contrib.sh`, the configure line, the base image), in the repository that owns the Dockerfile (`CNT-NNN` for swarm-routing/sim-containers) |
| A change in a repository nothing consumes at a version: swarm-routing/.github (reusable workflows at `@main`), the site's Pages deploy, swarm-routing/skills (the plugin), swarm-routing/benchmarks (datasets), swarm-routing/ns3-upstream-report | **no** for its own changes |
| A bug or change that never reached a published version (caught on `main`, in a PR, in a campaign before the next release) | **no**: an ordinary `bug` issue |
| A trivial change with no behaviour: a typo, a comment, wording in docs, with no effect on any behaviour, output, number or released artifact | **no** |

Whether a defect reached a published version is read from the record: a
release tag contains the commit that introduced it, or, for a port recipe,
a registry baseline does.

**Worked example.** AntHocNet bumps its swarm-core lock and something
breaks. The suspect is a bug in the released swarm-core, so the RCAPA is an
`SWC-NNN` in swarm-routing/swarm-adapter-ns3, opened from the consumer's
finding and verified with the consumer's failing check on the new release
against the old one.

### Where it lives

- The RCAPA lives in the **library's repository** (the one that owns the defect):
  `docs/rcapa/rcapa-<short-description>.md`, with an index,
  `docs/rcapa/README.md`, one row per RCAPA.
- IDs are `<PREFIX>-NNN`, numbered per repository from 001, never reused.
  The prefixes are one table in CONTRIBUTING ("RCAPA"), for the repositories
  where RCAPA applies; a new library adds its row there.
- ns-3 bugs keep `NS3-NNN` and process defects `PROC-NNN` in
  swarm-routing/sim-tools (`docs/ns3-bugs.md`, `docs/ns3-rcapa/`), as
  before.

### Ticket, form and template

- **The ticket comes first**: an issue in the owning repository, from the
  form *Regression in a release (RCAPA)* (`ISSUE_TEMPLATE/rcapa-regression.yml`),
  titled `[rcapa] <PREFIX>-NNN <short description>`, labels `rcapa` and
  `bug`. ns-3 bugs keep their form, *ns-3 bug (RCAPA)*.
- The document follows `templates/rcapa/_template.md`, generalised from
  ns3-tools' `docs/ns3-rcapa/_template.md`: summary, problem and detection,
  reproduction, five whys with cited evidence, diagrams, corrective and
  preventive actions, timeline, links. org-sync seeds `docs/rcapa/README.md`
  and `docs/rcapa/_template.md` into every repository it manages, once:
  seeds, so a repository's own index is never overwritten.
- References are fully qualified, as in the ns-3 register:
  `swarm-routing/<repo>#N` for ours, a link whose text is `nsnam/ns-3-dev#N`
  to the full GitLab URL for ns-3's.
- **The ticket stays open until the corrective action is merged and a
  release carries the fix** (PROC-001's rule, generalised): a fix on `main`
  is a step; the regression is closed when a published version no longer
  has it.

### Each project states its own flow

Every repository has `docs/rcapa/README.md`, its own from the seed on,
linked from its README through the org-sync managed Develop section. Where
RCAPA applies, it states the flow: what the library publishes and who pins
it, its ID prefix, where the ticket is opened, what verifies a regression
(the consumer's failing check, the library's own gates), its corrective and
preventive steps, how the ticket closes, a mermaid sequence diagram, and the
index. A library whose port is not published yet says its flow starts then.
Where RCAPA does not apply (the table above), the page says so plainly, with
the reason, and where RCAPA applies instead (a library the repository
consumes, the ns-3 register).

### Badges

Every repository's README shows "open RCAPA" (its open issues labelled
`rcapa`, linking `docs/rcapa/README.md`) in the Community & docs group;
swarm-routing/sim-tools also shows "ns-3 bugs" (open issues labelled
`ns3-upstream`, the `NS3-NNN` tickets, linking `docs/ns3-bugs.md`). Both are
counts in a neutral colour.

### Checks

`tools/docs-review/check_docs.py` checks that `docs/rcapa/README.md` exists
and that the README links it (a failure, `RCAPA_LEVEL`; swarm-routing/ns3-dev and
swarm-routing/packages, image and package listings rather than code
repositories, are excluded by name: `RCAPA_EXEMPT`), and warns on a seed TODO left
in it or an `rcapa-*.md` missing from its index.

## Consequences

- A regression in a published library has one record that answers what
  broke, for which consumer, why our gates let it out and which release
  fixes it, in that library's repository.
- Unreleased bugs stay cheap: no extra ceremony for what `main` catches
  before a release, which is most of them.
- Every repository gets two seeded files under `docs/rcapa/` through the
  org-bot refresh; a repository that never has a released regression keeps
  an index with no rows.
- swarm-routing/sim-containers copies the org forms by hand; it re-copies
  the new form under swarm-routing/sim-containers#177.
- An agent decides "published or not" from the consumers' pins and the
  release tags, not from memory; the pitfall line in
  `templates/agents/agent-defaults.md` says so.
- Images, the reusable workflows, the site, the plugin, the datasets and the
  upstream bridge carry no RCAPA for their own changes; their regressions
  are ordinary bugs, and an image's only when its composition is the cause.
