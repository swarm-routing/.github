// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
#include "protocol-hello.h"

#include "ns3/swarm-routing-base.h"

namespace ns3 {

std::string ProtocolHelloBaseName() {
    return SwarmRoutingBase::GetTypeId().GetName();
}

}  // namespace ns3
