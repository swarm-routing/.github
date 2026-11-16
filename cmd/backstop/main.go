// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command backstop dispatches a scheduled workflow whose own schedule did not run
// (see internal/backstop and .github/backstop.toml).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/backstop"
)

func main() {
	os.Exit(backstop.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
