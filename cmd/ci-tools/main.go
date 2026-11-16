// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command ci-tools is the ci-tools image's entrypoint: `ci-tools <tool>
// [args...]` runs /usr/local/bin/<tool>; `ci-tools list` prints the tools.
package main

import (
	"os"
	"syscall"

	"github.com/swarm-routing/.github/internal/dispatch"
)

func main() {
	os.Exit(dispatch.Main(os.Args[1:], "/usr/local/bin", os.Environ(), os.Stdout, os.Stderr, syscall.Exec))
}
