# Upstream ns-3 bugs the org found

A fixture shaped like swarm-routing/sim-tools docs/ns3-bugs.md.

## Index

| ID | Title | ns-3 versions | Modules | Status | Workaround in our repositories | Upstream | Investigation and fixes | RCAPA |
|----|-------|---------------|---------|--------|--------------------------------|----------|-------------------------|-------|
| NS3-001 | AODV livelocks in an ICMP storm | 3.49 (run); not 3.48 | aodv | open upstream; worked around | `routing-bench` guards the `aodv` arm ([swarm-routing/sim-tools#322](https://github.com/swarm-routing/sim-tools/pull/322)) | [nsnam/ns-3-dev#1408](https://gitlab.com/nsnam/ns-3-dev/-/work_items/1408) | [x](https://example.org/x) | [aodv-icmp-livelock](ns3-rcapa/ns3-rcapa-aodv-icmp-livelock.md) |
| NS3-002 | Sockets ordered by heap address \| a pipe kept | 3.42, 3.48 | dsdv | reported; see [the candidates](#candidates) | `--isolateArms` | none | none | none yet |

## Candidates: not yet shown to be ns-3's

| Finding | ns-3 | Where | Open question |
|---------|------|-------|---------------|
| a delay shift | 3.42 → 3.48 | here | bisect |

## Fixed upstream before we recorded them

| Bug | ns-3 | Fixed in | Upstream | Where found | Workaround in our repositories |
|-----|------|----------|----------|-------------|--------------------------------|
| 802.11b HR/DSSS frames dropped | 3.42 (run) | 3.43 | [nsnam/ns-3-dev#1095](https://gitlab.com/nsnam/ns-3-dev/-/work_items/1095) | here | strict XFAIL, see [the register](./ns3-rcapa/README.md) |

## Process RCAPAs (ours)

| ID | Title | Status | RCAPA ticket | RCAPA |
|----|-------|--------|--------------|-------|
| PROC-001 | not an ns-3 bug | open | none | none |
