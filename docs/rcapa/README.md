# RCAPA: does not apply to swarm-routing/.github's own changes

An **RCAPA** (root cause analysis with corrective and preventive actions) is
required for a regression in a **published library**: a version another
project consumes (a swarm-core or ns3-tools release through its lock or PyPI,
a protocol core's vcpkg port), and for every upstream ns-3 bug. The rule and
its decision table are in [CONTRIBUTING.md, "RCAPA"](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md#rcapa) ([ADR-0003](https://github.com/swarm-routing/.github/blob/main/docs/adr/0003-rcapa-for-ns3-bugs-and-released-regressions.md)).

**RCAPA does not apply to this repository's own changes**, because
nothing consumes it at a version. Its reusable workflows are called at
`@main`, its templates reach other repositories through org-bot's refresh
PRs, and it cuts no release. A defect here is an ordinary `bug` issue, fixed
on `main`.

**Where RCAPA applies instead:** an RCAPA for a library defect lives in that library's repository
(swarm-core, ns3-tools, a protocol core's port; CONTRIBUTING "RCAPA", the
prefix table); an ns-3 bug is an `NS3-NNN` in swarm-routing/ns3-tools.

The "open RCAPA" badge in the README counts this repository's open issues
labelled `rcapa`, so it reads 0 here.
