// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command security-alerts keeps one ticket per open security alert in every
// org repository (see internal/securityalerts).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/securityalerts"
)

func main() {
	os.Exit(securityalerts.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
