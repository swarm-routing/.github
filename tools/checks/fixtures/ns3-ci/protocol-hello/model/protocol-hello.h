// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
#ifndef PROTOCOL_HELLO_H
#define PROTOCOL_HELLO_H

#include <string>

namespace ns3 {

/// The TypeId name of swarm-core's SwarmRoutingBase, read through the
/// library: proves the module links swarm-core.
std::string ProtocolHelloBaseName();

}  // namespace ns3

#endif  // PROTOCOL_HELLO_H
