// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command branch-sweep deletes the org's stale branches (see internal/branchsweep).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/branchsweep"
)

func main() {
	os.Exit(branchsweep.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
