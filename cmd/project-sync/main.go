// Copyright (c) 2026 Daniel Joppi (https://github.com/swarm-routing)
// SPDX-License-Identifier: MIT OR GPL-2.0-only

// Command project-sync generates the org Project from the record (see internal/projectsync).
package main

import (
	"net/http"
	"os"
	"time"

	"github.com/swarm-routing/.github/internal/projectsync"
)

func main() {
	os.Exit(projectsync.Main(os.Args[1:], os.Getenv, &http.Client{Timeout: 60 * time.Second},
		"https://api.github.com", os.Stdout, os.Stderr))
}
