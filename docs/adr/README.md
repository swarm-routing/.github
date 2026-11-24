# Architecture decision records

One file per decision, numbered in order, never renumbered. A decision that
changes is superseded by a new ADR, not edited. Start from
[`0000-template.md`](0000-template.md).

The ADRs here are the org's: a decision recorded in `swarm-routing/.github`
applies to every repository unless it says otherwise.

| ADR | Decision |
|-----|----------|
| [0001](0001-record-architecture-decisions.md) | Record architecture decisions |
| [0002](0002-pipelines-are-go.md) | Pipelines are written in Go; their image is distroless |
| [0003](0003-rcapa-for-ns3-bugs-and-released-regressions.md) | An RCAPA for every ns-3 bug and every regression in a published library |
| [0004](0004-callers-pin-the-org-workflows-by-commit.md) | Callers pin the org's reusable workflows and actions by commit |
| [0005](0005-the-mcp-and-agent-tooling-standard.md) | Agent sessions use a small, measured set of MCP servers and tools (accepted 2026-11-22; amended the same day: swarm-mcp moves to swarm-routing/swarm-mcp, which the plugin will pin) |
| [0006](0006-one-wire-format-rule-and-a-daemon-only-envelope.md) | Keep one version byte per protocol message; put a shared envelope only on the daemon's socket (accepted 2026-11-24, #689) |
