// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command check-headers is the licence-header gate (see internal/checkheaders):
// `check-headers --dual core/ --core core/ [--core-dep DIR] [.]`, `--self-test`.
package main

import (
	"os"

	"github.com/swarm-routing/.github/internal/checkheaders"
)

func main() {
	os.Exit(checkheaders.Main(os.Args[1:], os.Stdout, os.Stderr))
}
