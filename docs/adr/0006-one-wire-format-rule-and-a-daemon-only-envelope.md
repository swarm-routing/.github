# 0006. Keep one version byte per protocol message; put a shared envelope only on the daemon's socket

- **Status:** proposed (the choice in "Options" is the maintainer's; the
  recommendation is option B)
- **Date:** 2026-11-24
- **Issue:** #689 (part of #672, Phase 1; maintainer decision 2 of 2026-11-22);
  swarm-routing/swarm-core#52, swarm-routing/swarm-core#3

## Context

**The rule that stands.** Org golden rule 3 (CONTRIBUTING invariant 2): a
control header is a simulator-independent POD struct with bounds-checked
little-endian readers and writers, a leading version byte, and deterministic
roundtrip and fuzz tests; a changed field or unit bumps the version byte.
AntHocNet ADR-0006 ("A 1-byte on-wire protocol version, no negotiation")
put `kWireVersion` at offset 0, checked before any length field, a mismatch
being a dropped packet. It considered and rejected "a multi-byte magic +
version envelope (e.g. 4 bytes)" because it "costs airtime on every ant in a
protocol whose overhead we benchmark". swarm-core's `core/swarm-wire.h`
(`WireWriter::version`, `WireReader::expectVersion`) is the helper every
protocol codec uses for that byte.

**The proposal.** #672 Phase 1 and swarm-routing/swarm-core#3 propose a
4-byte common framing header (`magic`, `protocol_id`, `version`, `flags`),
and the protocol chores (swarm-routing/AntHocNet#1117, swarm-routing/ARA#220,
swarm-routing/BeeAdHoc#198, swarm-routing/Termite#185,
swarm-routing/HOPNET#188) ask each protocol to adopt it before its wire
freeze. Its case: a receiver that hears several protocols, or stray traffic,
on one socket can reject a foreign packet at once and hand the rest to the
right parser; a Wireshark dissector can key on it (#689, comment of
2026-11-22).

**What was decided on 2026-11-22** (#672, decision 2): each protocol keeps
its own leading version byte; if the envelope is adopted it carries its own
version byte and wraps the protocol message rather than replacing that
message's version; adopting it bumps every protocol's wire version, with
roundtrip and fuzz tests. Decision 4 of the 21 (same day): published numbers
come from ns-3 only, because a daemon on a wall clock is not reproducible from
its seed. ROADMAP: CORE/EMANE and Shadow run the swarm-routingd binary.

**What is left open, and this ADR settles:** whether an envelope is adopted,
and on which runtimes it is on the wire.

**The cost.** Each protocol's smallest frames, read from its codec on `main`
(2026-11-24), and what 4 envelope bytes add to each:

| Protocol | Message (codec constant) | Bytes today | +4 bytes |
|----------|--------------------------|------------:|---------:|
| AntHocNet (`kWireVersion` 0x04) | any ant, empty arrays (`docs/wire-format.md`) | 41 | +9.8 % |
| | hello with the kinematics section, no adverts | 66 | +6.1 % |
| | largest accepted frame | 3209 | +0.1 % |
| ARA (`kAntWireVersion` 1) | FANT / BANT, fixed size (`kAntWireSize`) | 16 | +25.0 % |
| BeeAdHoc (each `kWireVersion` 1) | swarm, empty route (`Swarm::kFixedWireSize`) | 15 | +26.7 % |
| | scout, empty route (`Scout::kFixedWireSize`) | 21 | +19.0 % |
| | source-route trailer on every data packet (`Trailer::kFixedWireSize`) | 8 | +50.0 % |
| Termite (`kPacketWireVersion` 1) | the header on every packet, data included (`kPacketWireSize`) | 23 | +17.4 % |
| HOPNET (`kWireVersion` 2) | ant, empty path (`hopnet-ant.h`) | 32 | +12.5 % |
| | data header, empty route (`kDataWireVersion` 1, `hopnet-data.h`) | 17 | +23.5 % |

Variable parts grow every frame further (AntHocNet 12 bytes per hop, BeeAdHoc
4 per route node, HOPNET 12 per path entry and 4 per route node), so the
relative cost falls as frames grow; the absolute cost is 4 bytes on every
frame that carries the envelope. AntHocNet's NRL counts control bytes, ARA's
fidelity sheet names "routing bits / data bits" (its "Overhead metrics" row), and Termite
and BeeAdHoc would pay it on data packets too.

## Options

**A. The envelope on every runtime, ns-3 included.** Every protocol codec
writes and reads it. Every protocol's wire version bumps; every published
overhead number (NRL, routing bytes) changes by the table above and is a new
run, never an edit (benchmarks golden rule 10); each protocol's next release
carries the bump, before its wire freeze. Gains: one framing everywhere; a
pcap from ns-3 and one from Linux look alike. Costs: the airtime above in the
only runtime whose numbers are published, which is the cost AntHocNet
ADR-0006 refused, for a benefit (several protocols on one socket) that ns-3
never has: each ns-3 protocol binds its own socket, one build per run.

**B. The envelope only on the daemon's socket (recommended).** The protocol
messages stay byte-for-byte as they are on every runtime. swarm-routingd, and
whatever runs its binary (CORE/EMANE, Shadow, the Raspberry Pi testbed #325),
wraps each protocol message in the envelope when it sends on its UDP socket
and strips it on receipt, before the protocol's own decoder sees the bytes.
ns-3 numbers do not move; the daemon's overhead is the table above, stated in
its docs and subtracted (a known constant per frame) wherever a parity check
compares Linux bytes with ns-3 bytes (#672 Phase 2, #268's scenes).

**C. No envelope.** The daemon gives each protocol its own UDP port; the
per-protocol version byte is the only check. Zero cost and no new code, but
stray traffic on a port is rejected only by a 1-in-256 version byte match and
then the protocol's bounds checks, and a dissector keys on port numbers that
a deployment may change.

## Decision (proposed: option B)

1. **The rule that stands, unchanged.** Every protocol message starts with
   its protocol's own version byte, read first and rejected in O(1) on
   mismatch (golden rule 3, AntHocNet ADR-0006). Nothing in this ADR changes
   a protocol's bytes.
2. **The envelope** is 4 single-byte fields, written and
   read by swarm-core (`core/swarm-envelope.h`, on `swarm-wire.h`), followed
   by the protocol message byte-for-byte:

   | Offset | Field | Type | Meaning |
   |-------:|-------|------|---------|
   | 0 | `envelope_version` | `u8` | `0x01`. Read first; any other value is a dropped packet, in O(1), before anything else is read (as AntHocNet ADR-0006). A change to the envelope's layout or meaning bumps it. |
   | 1 | `magic` | `u8` | `0x53` (`'S'`). With byte 0 it rejects stray traffic that happens to start with `0x01` (1 in 65 536 random packets pass both). |
   | 2 | `protocol_id` | `u8` | Which protocol's decoder gets the rest. `0x00` is invalid. |
   | 3 | `flags` | `u8` | Optional envelope features. Version `0x01` defines none: a receiver drops a packet with any bit set that its envelope version does not define. A bit is defined only with an envelope version bump; the first candidate is an authentication trailer for #272. |
   | 4 | the protocol message | bytes | Unchanged, starting with that protocol's own version byte. |

3. **`protocol_id` assignments** live in swarm-core: the constants in
   `core/swarm-envelope.h` and a table in `docs/protocol-ids.md`, allocated by
   a PR to swarm-routing/swarm-core and never reused. The first five, in
   release order: `0x01` AntHocNet, `0x02` ARA, `0x03` BeeAdHoc, `0x04`
   Termite, `0x05` HOPNET. POSANT, BeeSensor and Q-Swarm get theirs when
   their `core/` lands (decision 1 of 2026-11-22). `0xF0`–`0xFE` are for
   local experiments and never ship; `0xFF` is reserved. Comparator arms run
   in ns-3 only and get none.
4. **Where it is on the wire:** only on swarm-routingd's control socket, and
   so on every runtime that runs its binary (CORE/EMANE, Shadow, real boards).
   Never in ns-3, never in a protocol's codec, never in a published number.
   If a protocol's data-plane header (Termite's header, BeeAdHoc's trailer,
   HOPNET's data header) crosses a Linux host through the daemon's socket, it
   is enveloped too; whether it does is swarm-routing/swarm-routingd#3's
   design, and the cost is the table above.
5. **Versioning consequences.** No protocol's wire version bumps: under
   option B no protocol's bytes change, and golden rule 3 bumps a version on
   a changed field or unit. This reads decision 2's "adopting it bumps every
   protocol's wire version" as applying to option A, where the codecs change;
   the maintainer confirms that reading when accepting this ADR. No protocol
   release carries a wire change for it, a protocol's `1.0.0` wire freeze is
   unaffected, and no recorded benchmark is re-run. swarm-core gains the
   envelope as an addition (a minor release under `docs/api-policy.md`).
6. **Tests.** swarm-core: a deterministic roundtrip of the envelope for every
   assigned `protocol_id`, rejection tests (wrong version, wrong magic,
   `protocol_id` 0, an undefined flag, a buffer shorter than 4 bytes), and
   the envelope reader in the libFuzzer set of swarm-routing/swarm-core#9.
   swarm-routingd: per protocol, wrap then unwrap of that protocol's own
   roundtrip fixtures gives the same bytes, and its decoder accepts them.
7. **The Wireshark dissector** (#689, comment of 2026-11-22) becomes a
   follow-up issue in swarm-routingd once the envelope ships: one dissector
   for the envelope that hands the rest to one per protocol, each tested
   against that protocol's `docs/wire-format.md` and roundtrip fixtures.

## Consequences

- Every number published so far, and every ns-3 run to come, keeps its bytes:
  the ns-3 rung pays nothing, as AntHocNet ADR-0006 asked.
- A Linux host running several protocols, or hearing stray UDP, rejects a
  foreign packet in two byte compares and dispatches the rest by one byte.
- Linux and ns-3 frames differ by exactly 4 bytes per enveloped frame; a
  parity check that compares bytes subtracts them, and a pcap from the daemon
  needs the envelope stripped before an ns-3 tool reads it.
- The `protocol_id` table is one more registry to keep; swarm-core owns it.
- If the maintainer chooses option A instead, items 4 and 5 change: every
  protocol codec writes the envelope, every protocol bumps its wire version
  in its next release, every overhead number is re-run, and each protocol's
  `docs/wire-format.md` gains the 4 bytes. Option C drops items 2, 3, 6 and 7
  and swarm-routing/swarm-core#52 closes as not planned.
- The protocol chores (swarm-routing/AntHocNet#1117, swarm-routing/ARA#220,
  swarm-routing/BeeAdHoc#198, swarm-routing/Termite#185,
  swarm-routing/HOPNET#188) lose their "adopt the 4-byte header" item under B
  and C: the protocols change nothing.
