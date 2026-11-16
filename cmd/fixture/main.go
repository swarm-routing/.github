// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command fixture is the ci-tools image's fixture tool: `fixture FILE...`
// prints "<path> <newlines> <sha256>" per file (see internal/fixture).
package main

import (
	"os"

	"github.com/swarm-routing/.github/internal/fixture"
)

func main() {
	os.Exit(fixture.Run(os.Args[1:], os.Stdout, os.Stderr))
}
