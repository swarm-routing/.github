# 0003. An RCAPA for every ns-3 bug and every regression in a published release

- **Status:** accepted
- **Date:** 2026-11-16
- **Issue:** #538

## Context

Since 2026-11-16 every defect in upstream ns-3, and every investigation of
one, gets an **RCAPA** (root cause analysis with corrective and preventive
actions): a ticket first, then a document with five cited whys, a
reproducer, diagrams, the actions and a timeline. The register lives in
swarm-routing/ns3-tools (`docs/ns3-bugs.md`, `docs/ns3-rcapa/`, IDs
`NS3-NNN`), and a defect in how we carry a report is a `PROC-NNN` there
(PROC-001, swarm-routing/ns3-tools#247).

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

## Decision

### When an RCAPA is required

| Defect | RCAPA |
|--------|-------|
| A bug in upstream ns-3, or an investigation of one | **always**: `NS3-NNN` in swarm-routing/ns3-tools, unchanged |
| A defect in how we carry an ns-3 report upstream | **always**: `PROC-NNN` in swarm-routing/ns3-tools, unchanged |
| A **regression in a published release**: something that worked in a released version (a GitHub release, its Zenodo DOI, a PyPI package, a vcpkg port) and broke after a change, so the defect is in a published release or was found against one | **yes**: `<PREFIX>-NNN` in the repository that owns the defect |
| A bug or change that never reached a release (caught on `main`, in a PR, in a campaign before the next release) | **no**: an ordinary `bug` issue |
| A trivial change with no behaviour: a typo, a comment, wording in docs, with no effect on any behaviour, output, number or released artifact | **no** |

When in doubt whether a defect reached a release, compare the commit that
introduced it with the repository's latest release tag: it is a released
regression when that tag contains it.

### Where it lives

- The RCAPA lives in the **repository that owns the defect**:
  `docs/rcapa/rcapa-<short-description>.md`, with an index,
  `docs/rcapa/README.md`, one row per RCAPA.
- IDs are `<PREFIX>-NNN`, numbered per repository from 001, never reused.
  The prefixes are one table in CONTRIBUTING ("RCAPA"); a new repository
  adds its row there.
- ns-3 bugs keep `NS3-NNN` and process defects `PROC-NNN` in
  swarm-routing/ns3-tools (`docs/ns3-bugs.md`, `docs/ns3-rcapa/`), as
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

Every repository has `docs/rcapa/README.md`, its own from the seed on: what
counts as published for that project (its release channels: a GitHub
release and its Zenodo DOI, PyPI, a vcpkg port, images, the site deploy, a
dataset release, the plugin version), its ID prefix, where the ticket is
opened, what verifies a regression (the CI check, gate or reproducer that
shows it), its corrective and preventive steps, how the ticket closes, a
mermaid sequence diagram of that flow, and the index. A project that has
published nothing yet says so: its flow starts at its first release. The
README links it, through the org-sync managed Develop section.

### Badges

Every repository's README shows "open RCAPA" (its open issues labelled
`rcapa`, linking `docs/rcapa/README.md`) in the Community & docs group;
swarm-routing/ns3-tools also shows "ns-3 bugs" (open issues labelled
`ns3-upstream`, the `NS3-NNN` tickets, linking `docs/ns3-bugs.md`). Both are
counts in a neutral colour.

### Checks

`tools/docs-review/check_docs.py` checks that `docs/rcapa/README.md` exists
and that the README links it (a warning while the flows roll out, a failure
once every repository has one: `RCAPA_LEVEL`), and warns on a seed TODO left
in it or an `rcapa-*.md` missing from its index.

## Consequences

- A released regression has one record that answers what broke, for whom,
  why our gates let it out and which release fixes it, in the repository a
  reader of that release looks at.
- Unreleased bugs stay cheap: no extra ceremony for what `main` catches
  before a release, which is most of them.
- Every repository gets two seeded files under `docs/rcapa/` through the
  org-bot refresh; a repository that never has a released regression keeps
  an index with no rows.
- swarm-routing/ns3-containers copies the org forms by hand; it re-copies
  the new form under swarm-routing/ns3-containers#177.
- An agent decides "released or not" from the release tags, not from
  memory; the pitfall line in `templates/agents/agent-defaults.md` says so.
