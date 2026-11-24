// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: GPL-2.0-only
#include "ns3/protocol-hello.h"
#include "ns3/routing-bench-arm.h"
#include "ns3/test.h"

using namespace ns3;

class ProtocolHelloTestCase : public TestCase {
public:
    ProtocolHelloTestCase() : TestCase("swarm-core and routing-bench link") {}

private:
    void DoRun() override {
        NS_TEST_ASSERT_MSG_EQ(ProtocolHelloBaseName(), "ns3::SwarmRoutingBase", "swarm-core's base class");
        bench::ArmRegistry registry;
        NS_TEST_ASSERT_MSG_EQ(registry.Add("hello", "a null factory", nullptr), false,
                              "routing-bench refuses an arm without a factory");
        NS_TEST_ASSERT_MSG_EQ(registry.Has("hello"), false, "and does not register it");
    }
};

class ProtocolHelloTestSuite : public TestSuite {
public:
    ProtocolHelloTestSuite() : TestSuite("protocol-hello", Type::UNIT) {
        AddTestCase(new ProtocolHelloTestCase, TestCase::Duration::QUICK);
    }
};

static ProtocolHelloTestSuite g_protocolHelloTestSuite;
