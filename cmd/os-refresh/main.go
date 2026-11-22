// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command os-refresh dispatches an image repository's OS security refresh when
// Trivy finds fixable OS vulnerabilities in its published images (see
// internal/osrefresh).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/osrefresh"
)

func main() {
	os.Exit(osrefresh.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
