// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command action-pins keeps the template pins at the workflows' pins and
// sweeps the org's Dependabot pull requests (see internal/actionpins).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/actionpins"
)

func main() {
	os.Exit(actionpins.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
