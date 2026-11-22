// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command ci-tools-digest moves every ci-tools image pin in the org's public
// repositories to the promoted image, by pull request (see
// internal/citoolsdigest).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/citoolsdigest"
)

func main() {
	os.Exit(citoolsdigest.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", "https://ghcr.io", os.Stdout, os.Stderr))
}
