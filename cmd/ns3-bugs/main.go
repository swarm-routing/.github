// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command ns3-bugs renders the install guide's "Known simulator bugs" table
// from swarm-routing/sim-tools docs/ns3-bugs.md (see internal/ns3bugs):
// `ns3-bugs REGISTER.md [--base URL] [--write FILE | --check FILE]`.
package main

import (
	"os"

	"github.com/swarm-routing/.github/internal/ns3bugs"
)

func main() {
	os.Exit(ns3bugs.Main(os.Args[1:], os.Stdout, os.Stderr))
}
