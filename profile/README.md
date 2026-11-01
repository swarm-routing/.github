# swarm-routing

Swarm-intelligence and adaptive routing protocols for MANETs and LEO
constellations, implemented cleanly on **ns-3** and benchmarked against each
other on identical seeds.

The org grew out of [**AntHocNet**](https://github.com/danieljoppi/AntHocNet)
(Di Caro, Ducatelle & Gambardella, 2005), the source repository: its shared
infrastructure, comparator arms and benchmark tooling are moving here so each
protocol can be its own citable repository.

| Repository | What it is |
|---|---|
| [ns3-containers](https://github.com/swarm-routing/ns3-containers) | `ghcr.io/swarm-routing/ns3-dev` images: ns-3 pre-built (debug / sanitized / optimized), contrib modules compile in seconds |
| [ns3-swarm-core](https://github.com/swarm-routing/ns3-swarm-core) | The `swarm-core` contrib module: shared primitives (visited path, LE codecs, pheromone table, route decision) and ns-3 cross-layer glue |
| [ns3-tools](https://github.com/swarm-routing/ns3-tools) | Diagnostic probes, comparison arenas, the `ns3-tool` CLI (sweep, compare, diagnose, scaffold) |
| [ARA](https://github.com/swarm-routing/ARA) | Ant-Colony-Based Routing Algorithm (Güneş et al., 2002) |
| [BeeAdHoc](https://github.com/swarm-routing/BeeAdHoc) | Honeybee routing (Wedde & Farooq, 2005) |
| [benchmarks](https://github.com/swarm-routing/benchmarks) | Immutable 20-seed datasets, paired verdicts, reproducibility manifests |
| [swarm-routing.github.io](https://swarm-routing.github.io) | Colony Arena: interactive docs, visualizers, leaderboard |
| [AntHocNet](https://github.com/danieljoppi/AntHocNet) | The reference AntHocNet implementation (joins the org after the cutover) |

Every protocol is deterministic for a fixed seed, MIT-licensed, and compared by
paired per-seed deltas over ≥ 20 seeds. Conventions:
[CONTRIBUTING.md](https://github.com/swarm-routing/.github/blob/main/CONTRIBUTING.md).
