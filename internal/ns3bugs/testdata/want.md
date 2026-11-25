<!-- Generated from swarm-routing/sim-tools docs/ns3-bugs.md by swarm-routing/.github
     cmd/ns3-bugs (swarm-routing/.github#884); never edit by hand: a change goes to the register. -->
Upstream ns-3 defects our repositories meet, from the org's [ns-3 bug register](https://github.com/swarm-routing/sim-tools/blob/main/docs/ns3-bugs.md).
Each ID links its RCAPA (the reproduction, the root cause, the upstream report).

| ID | What breaks | ns-3 versions | Status | Our fix or workaround |
|----|-------------|---------------|--------|-----------------------|
| [NS3-001](https://github.com/swarm-routing/sim-tools/blob/main/docs/ns3-rcapa/ns3-rcapa-aodv-icmp-livelock.md) | AODV livelocks in an ICMP storm | 3.49 (run); not 3.48 | open upstream; worked around | `routing-bench` guards the `aodv` arm ([swarm-routing/sim-tools#322](https://github.com/swarm-routing/sim-tools/pull/322)) |
| NS3-002 | Sockets ordered by heap address \| a pipe kept | 3.42, 3.48 | reported; see [the candidates](https://github.com/swarm-routing/sim-tools/blob/main/docs/ns3-bugs.md#candidates) | `--isolateArms` |

Fixed upstream, but present in an older ns-3 release you may still pin:

| What breaks | ns-3 versions | Fixed in | Our fix or workaround |
|-------------|---------------|----------|-----------------------|
| 802.11b HR/DSSS frames dropped | 3.42 (run) | 3.43 | strict XFAIL, see [the register](https://github.com/swarm-routing/sim-tools/blob/main/docs/ns3-rcapa/README.md) |
